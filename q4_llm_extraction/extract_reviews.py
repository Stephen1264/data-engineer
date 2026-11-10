"""Q4 按规则、已校验的模型缓存和本地 LLM 处理 Olist 评价。"""

import argparse
import csv
import hashlib
import http.client
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
from urllib.parse import urlsplit

from download_data import ensure_dataset
from q4_llm_extraction.review_rules import (
    CATEGORIES, SELLER_ACTIONS, SEVERITIES, TIME_EVIDENCE, baseline_sentiment,
    detect_issues, quote_is_safe, review_cues,
)

HERE = Path(__file__).resolve().parent
MODEL_CACHE = HERE / "llm_cache.json"
OUTPUT = HERE / "extracted_issues.json"
ISSUE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"enum": list(CATEGORIES)},
        "severity": {"enum": list(SEVERITIES)},
        "evidence_quote": {"type": "string"},
        "evidence_quote_en": {"type": "string"},
    },
    "required": ["category", "severity", "evidence_quote", "evidence_quote_en"],
    "additionalProperties": False,
}
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "issues": {"type": "array", "maxItems": 3, "items": ISSUE_SCHEMA},
        "sentiment_score": {"type": "number"},
        "actionable_for_seller": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
    "required": ["id", "issues", "sentiment_score", "actionable_for_seller", "confidence"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {"reviews": {"type": "array", "items": RESULT_SCHEMA}},
    "required": ["reviews"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Review:
    review_id: str
    score: int
    text: str

    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.score}\0{self.text}".encode("utf-8")).hexdigest()


def load_reviews() -> tuple[list[Review], int]:
    path = ensure_dataset("olist") / "olist_order_reviews_dataset.csv"
    latest = {}
    count = 0
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            score = int(row["review_score"])
            if not 1 <= score <= 3:
                continue
            count += 1
            review_id = row["review_id"]
            text = row["review_comment_message"].strip()
            key = (row["review_answer_timestamp"], bool(text), row["review_creation_date"], row["order_id"])
            if review_id not in latest or key > latest[review_id][0]:
                latest[review_id] = key, Review(review_id, score, text)
    return [latest[review_id][1] for review_id in sorted(latest)], count


def call_local_llm(url: str, payload: dict, timeout: float) -> dict:
    target = urlsplit(url)
    if (
        target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"}
        or target.username or target.password or target.path not in {"", "/"}
        or target.query or target.fragment
    ):
        raise ValueError("LLM 地址必须是本机 HTTP 服务根地址")
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("GEKKO_LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    connection = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=timeout)
    try:
        connection.request(
            "POST", "/v1/chat/completions",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers,
        )
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f"本地推理返回 HTTP {response.status}")
        return json.loads(response.read())
    finally:
        connection.close()


def infer_batch(url: str, model: str, prompt: str, batch: list[Review], timeout: float) -> dict:
    items = [
        {"id": index, "score": review.score, "text": review.text}
        for index, review in enumerate(batch)
    ]
    return call_local_llm(url, {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "review_batch", "strict": True, "schema": SCHEMA}},
        "temperature": 0, "seed": 42, "max_tokens": 220 * len(batch) + 100,
    }, timeout)


def verify_prediction(value: dict, review: Review) -> dict:
    if not isinstance(value, dict):
        raise ValueError("模型记录类型错误")
    sentiment, confidence = value.get("sentiment_score"), value.get("confidence")
    if type(sentiment) not in {int, float} or not -1 <= sentiment <= 1:
        raise ValueError("情绪值超出范围")
    if type(confidence) not in {int, float} or not 0 <= confidence <= 1:
        raise ValueError("置信度超出范围")
    if type(value.get("actionable_for_seller")) is not bool or not isinstance(value.get("issues"), list):
        raise ValueError("模型字段类型错误")
    if len(value["issues"]) > 3:
        raise ValueError("单条评价的问题数超出上限")
    verified = []
    for issue in value["issues"]:
        if not isinstance(issue, dict) or set(issue) != set(ISSUE_SCHEMA["required"]):
            raise ValueError("模型问题字段错误")
        if issue["category"] not in CATEGORIES or issue["severity"] not in SEVERITIES:
            raise ValueError("模型问题类别或严重度无效")
        quote, translated = issue["evidence_quote"], issue["evidence_quote_en"]
        if not isinstance(quote, str) or not quote_is_safe(quote, review.text):
            raise ValueError("引用不在原文中、含隐私模式或长度异常")
        if not isinstance(translated, str) or not 1 <= len(translated.strip()) <= 360:
            raise ValueError("英文证据缺失或过长")
        verified.append(issue)
    return {
        "issues": verified, "sentiment_score": sentiment,
        "actionable_for_seller": value["actionable_for_seller"], "confidence": confidence,
    }


def score_candidate(review: Review, issues: list[dict]) -> int:
    if not 24 <= len(review.text) <= 1200:
        return 0
    missed = review_cues(review.text) - {issue["category"] for issue in issues}
    if not missed and (issues or len(review.text) < 65):
        return 0
    return 3 * min(len(missed), 3) + int(not issues) + int(review.score == 1)


def write_text_atomic(path: Path, text: str) -> None:
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as output:
        staged = Path(output.name)
        try:
            output.write(text)
        except Exception:
            output.close()
            staged.unlink(missing_ok=True)
            raise
    try:
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def read_cache(prompt_sha: str) -> dict:
    if MODEL_CACHE.is_file():
        payload = json.loads(MODEL_CACHE.read_text(encoding="utf-8"))
        if payload.get("prompt_sha256") == prompt_sha:
            return payload
    return {"model": None, "prompt_sha256": prompt_sha, "predictions": {}}


def cached_prediction(cache: dict, review: Review):
    entry = cache["predictions"].get(review.review_id)
    if entry is not None and entry["input_sha256"] == review.fingerprint():
        return verify_prediction(entry["result"], review)
    return None


def run_model(args, prompt: str, pending: list[Review], cache: dict, stats: Counter, deadline: float) -> None:
    for start in range(0, len(pending), args.batch_size):
        remaining = deadline - monotonic()
        if remaining < 2:
            break
        batch = pending[start:start + args.batch_size]
        stats["requests"] += 1
        stats["llm_attempted"] += len(batch)
        try:
            response = infer_batch(args.llm_url, args.model, prompt, batch, min(90, remaining - 1))
            usage = response.get("usage", {})
            stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
            stats["completion_tokens"] += usage.get("completion_tokens", 0)
            predictions = json.loads(response["choices"][0]["message"]["content"])["reviews"]
            ids = [row["id"] for row in predictions]
            if len(ids) != len(batch) or any(type(idx) is not int for idx in ids) or sorted(ids) != list(range(len(batch))):
                raise ValueError("模型响应的批内 ID 错位")
        except (OSError, http.client.HTTPException, RuntimeError, ValueError, KeyError, IndexError, TypeError):
            stats["failed_batches"] += 1
            if stats["failed_batches"] >= 3 and not stats["llm_valid"]:
                break
            continue
        for row in predictions:
            review = batch[row["id"]]
            try:
                verified = verify_prediction(row, review)
            except (ValueError, TypeError):
                stats["rejected_predictions"] += 1
                continue
            cache["predictions"][review.review_id] = {
                "input_sha256": review.fingerprint(), "result": verified,
            }
            stats["llm_valid"] += 1
        if stats["requests"] % 20 == 0:
            print(f"Q4 模型已请求 {stats['llm_attempted']} 条，校验通过 {stats['llm_valid']} 条", flush=True)


def merge_result(review: Review, baseline: list[dict], prediction) -> tuple[dict, bool]:
    issues = {issue["category"]: issue for issue in baseline}
    base_categories = set(issues)
    sentiment = baseline_sentiment(review.score, review.text)
    confidence = 0.85 if issues else (0.3 if review.text else 0.0)
    if prediction and prediction["confidence"] >= 0.55:
        for issue in prediction["issues"]:
            issues.setdefault(issue["category"], issue)
    delivery = issues.get("delivery_late")
    if delivery and "missing_item" in issues and not TIME_EVIDENCE.search(delivery["evidence_quote"]):
        # 若同评有缺件证据，未收到的短语可能指部分商品。保留有明确时间证据的迟到。
        issues.pop("delivery_late")
    from_model = bool(issues.keys() - base_categories)
    if from_model:
        sentiment = prediction["sentiment_score"]
        confidence = prediction["confidence"]
    return {
        "review_id": review.review_id, "issues": list(issues.values()),
        "sentiment_score": sentiment, "actionable_for_seller": bool(issues.keys() & SELLER_ACTIONS),
        "confidence": confidence,
    }, from_model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-url", help="本地 llama.cpp HTTP 服务根地址")
    parser.add_argument("--model", default="qwen2.5-3b", help="本地服务的模型别名")
    parser.add_argument("--llm-limit", type=int, default=360, help="最多新推理的评论数")
    parser.add_argument("--batch-size", type=int, default=3, choices=range(1, 5))
    parser.add_argument("--time-limit", type=int, default=2280, help="本地处理最长秒数，最多 2280 秒")
    parser.add_argument("--refresh-llm", action="store_true", help="丢弃旧缓存并重新推理")
    parser.add_argument("--stats-json", type=Path, help="可选的本次运行统计文件")
    args = parser.parse_args()
    if args.llm_limit < 1 or not 1 <= args.time_limit <= 2280 or (args.refresh_llm and not args.llm_url):
        parser.error("请设置有效的批量、时间和本地模型选项")

    started = monotonic()
    prompt = (HERE / "prompt_template.txt").read_text(encoding="utf-8")
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    cache = read_cache(prompt_sha)
    reviews, raw_count = load_reviews()
    rules = {review.review_id: detect_issues(review.text) for review in reviews}
    candidates = []
    for review in reviews:
        rank = score_candidate(review, rules[review.review_id])
        if rank:
            shuffle = hashlib.sha256(("42:" + review.review_id).encode("ascii")).hexdigest()
            candidates.append((-rank, shuffle, review))
    candidates.sort(key=lambda row: row[:2])
    stats = Counter(
        raw_low_score=raw_count, unique_reviews=len(reviews),
        blank_reviews=sum(not review.text for review in reviews), llm_candidates=len(candidates),
        rules_with_issues=sum(bool(value) for value in rules.values()),
    )
    if args.llm_url:
        if args.refresh_llm or args.model != cache["model"]:
            cache = {"model": args.model, "prompt_sha256": prompt_sha, "predictions": {}}
        pending = [review for _, _, review in candidates if cached_prediction(cache, review) is None]
        run_model(args, prompt, pending[:args.llm_limit], cache, stats, started + args.time_limit)
        if pending and not stats["llm_valid"]:
            raise RuntimeError("本地模型无有效响应，原有结果保留")
        write_text_atomic(MODEL_CACHE, json.dumps(cache, ensure_ascii=False, indent=2, allow_nan=False) + "\n")

    rows = []
    for review in reviews:
        prediction = cached_prediction(cache, review)
        result, from_model = merge_result(review, rules[review.review_id], prediction)
        rows.append("  " + json.dumps(result, ensure_ascii=False, allow_nan=False))
        stats["with_issues"] += bool(result["issues"])
        stats["llm_enriched"] += from_model
        stats["cache_hits"] += prediction is not None
    write_text_atomic(OUTPUT, "[\n" + ",\n".join(rows) + "\n]\n")
    stats["elapsed_seconds"] = round(monotonic() - started, 3)
    if args.stats_json:
        write_text_atomic(args.stats_json, json.dumps(stats, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
