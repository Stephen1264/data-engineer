"""本地并行选择证据片段、翻译并生成 Q4 的可复跑缓存。"""

import argparse
import hashlib
import http.client
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic

from q4_llm_extraction.extract_reviews import (
    SPAN_CACHE, SPAN_PROMPT, SUPPORT_PROMPT, call_local_llm, load_reviews,
    span_prompt_digest, verify_prediction, write_text_atomic,
)
from q4_llm_extraction.review_rules import PRIVATE_QUOTE, SELLER_ACTIONS
from q4_llm_extraction.span_inference import (
    BOUNDARY, decode_selection, is_informative, request_payload, source_spans,
    support_payload, supported_issues,
)


def complete_packet(url, payload, size, deadline, stats):
    remaining = deadline - monotonic()
    if remaining < 2:
        return None
    stats.update(requests=1, unique_attempted=size)
    try:
        response = call_local_llm(url, payload, min(45, remaining), endpoint="/completion")
        timing = response.get("timings", {})
        stats.update({
            "prompt_tokens_evaluated": timing.get("prompt_n", 0),
            "prompt_tokens_reused": timing.get("cache_n", 0),
            "completion_tokens": timing.get("predicted_n", 0),
        })
        lines = response["content"].strip().splitlines()
        if len(lines) != size or response.get("truncated") or response.get("stopped_limit"):
            raise ValueError("批内行数不一致或响应被截断")
    except (OSError, http.client.HTTPException, RuntimeError, ValueError, KeyError, TypeError):
        stats["failed_packets"] += 1
        return None
    return lines


def classify_packet(url, prompt, batch, deadline):
    stats = Counter()
    items = [(review.text, source_spans(review.text)) for review in batch]
    lines = complete_packet(url, request_payload(prompt, items), len(batch), deadline, stats)
    accepted = []
    for review, (source, spans), line in zip(batch, items, lines or []):
        try:
            _, issues = decode_selection(line, source, spans)
        except ValueError:
            stats["invalid_rows"] += 1
            continue
        stats["rejected_spans"] += (len(line.split()) - 1 if not line.endswith(" 0") else 0) - len(issues)
        accepted.append((review.review_id, [review.fingerprint(), line]))
    return accepted, stats


def classify_reviews(args, prompt, identity, representatives, deadline, stats):
    selections = {}
    if args.checkpoint and args.checkpoint.is_file():
        checkpoint = json.loads(args.checkpoint.read_text(encoding="utf-8"))
        if checkpoint["identity"] != identity:
            raise ValueError("续跑文件的模型、提示词或批大小不同，请指定新的文件")
        for review in representatives:
            entry = checkpoint["selections"].get(review.review_id)
            if entry and entry[0] == review.fingerprint():
                decode_selection(entry[1], review.text, source_spans(review.text))
                selections[review.review_id] = entry
    pending = [review for review in representatives if review.review_id not in selections]
    stats["resumed_unique"] = len(selections)
    block_size = args.batch_size * args.workers * 5
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0, len(pending), block_size):
            if monotonic() >= deadline:
                break
            block = pending[start:start + block_size]
            tasks = [
                pool.submit(classify_packet, args.llm_url, prompt, block[i:i + args.batch_size], deadline)
                for i in range(0, len(block), args.batch_size)
            ]
            for task in tasks:
                rows, counts = task.result()
                selections.update(rows)
                stats.update(counts)
            if not selections:
                raise RuntimeError("本地模型未返回任何可用的分类，原缓存保留")
            if args.checkpoint:
                write_text_atomic(
                    args.checkpoint,
                    json.dumps({"identity": identity, "selections": selections}, ensure_ascii=False) + "\n",
                )
            print(f"Q4 编号选择 {len(selections):,}/{len(representatives):,} 组，失败批次 {stats['failed_packets']}", flush=True)
    return selections


def verify_packet(url, prompt, batch, deadline):
    stats = Counter()
    lines = complete_packet(url, support_payload(prompt, batch), len(batch), deadline, stats)
    accepted = []
    for (source, proposed), bits in zip(batch, lines or []):
        try:
            issues = supported_issues(bits, proposed)
        except ValueError:
            stats["invalid_rows"] += 1
            continue
        stats.update(proposed_issues=len(proposed), supported_issues=len(issues))
        accepted.append((source, issues))
    return accepted, stats


def verify_evidence(args, prompt, classified, deadline, stats):
    # 无类别提案的文本可直接沿用模型情绪；未完成复核的提案由已有规则兜底。
    verified = {source: (sentiment, []) for source, (sentiment, issues) in classified.items() if not issues}
    pending = [(source, issues) for source, (_, issues) in classified.items() if issues]
    stats["candidates"] = len(pending)
    block_size = args.batch_size * args.workers * 6
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0, len(pending), block_size):
            if monotonic() >= deadline:
                break
            block = pending[start:start + block_size]
            tasks = [
                pool.submit(verify_packet, args.llm_url, prompt, block[i:i + args.batch_size], deadline)
                for i in range(0, len(block), args.batch_size)
            ]
            for task in tasks:
                rows, counts = task.result()
                stats.update(counts)
                for source, issues in rows:
                    verified[source] = (classified[source][0], issues)
                stats["verified_unique"] += len(rows)
            print(f"Q4 证据复核 {stats['verified_unique']:,}/{len(pending):,} 组，失败批次 {stats['failed_packets']}", flush=True)
    if pending and not stats["verified_unique"]:
        raise RuntimeError("证据复核未返回任何有效结果，原缓存保留")
    return verified


def load_translator(path: Path):
    import ctranslate2
    import sentencepiece

    metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    if (metadata.get("from_code"), metadata.get("to_code")) != ("pt", "en"):
        raise ValueError("需要葡语到英语的 Argos 模型目录")
    processor = sentencepiece.SentencePieceProcessor(model_file=str(path / "sentencepiece.model"))
    translator = ctranslate2.Translator(
        str(path / "model"), device="cpu", compute_type="int8", inter_threads=2, intra_threads=4,
    )
    return processor, translator


def translate_quotes(quotes, processor, translator, deadline, stats):
    # Argos 训练单位为单句。两句才能说明数量差时分别翻译，再按原次序拼接。
    segments = {quote: [part.strip() for part in BOUNDARY.split(quote) if part.strip()] for quote in quotes}
    phrases = sorted({part for parts in segments.values() for part in parts}, key=lambda part: (len(part), part))
    translated = {}
    for start in range(0, len(phrases), 128):
        if monotonic() >= deadline:
            break
        batch = phrases[start:start + 128]
        # 全大写葡语会降低翻译质量。只改变译码输入，发布的引用保留原字形。
        translation_input = [source.lower() if source.isupper() else source for source in batch]
        results = translator.translate_batch(
            processor.encode(translation_input, out_type=str), beam_size=2, batch_type="tokens",
            max_batch_size=768, max_decoding_length=160, disable_unk=True,
        )
        for source, result in zip(batch, results):
            english = processor.decode(result.hypotheses[0]).replace("\u2581", " ")
            english = " ".join(english.split())
            if english and any(char.isalpha() for char in english) and not PRIVATE_QUOTE.search(english):
                translated[source] = english
    stats["unique_sentences_to_translate"] = len(phrases)
    stats["unique_sentences_translated"] = len(translated)
    return {
        quote: english for quote, parts in segments.items()
        if parts and all(part in translated for part in parts)
        and len(english := " ".join(translated[part] for part in parts)) <= 360
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-url", required=True, help="本地 llama.cpp 服务根地址")
    parser.add_argument("--model", default="qwen3-4b-instruct-2507", help="用于缓存记录和续跑校验的模型别名")
    parser.add_argument("--translation-model", required=True, type=Path, help="解压后的 Argos 葡语到英语模型目录")
    parser.add_argument("--batch-size", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--workers", type=int, default=12, choices=range(1, 25))
    parser.add_argument("--time-limit", type=int, default=2280, help="本次处理总时限，最多 2280 秒")
    parser.add_argument("--checkpoint", type=Path, help="可选续跑文件，建议放在仓库外")
    parser.add_argument("--stats-json", type=Path, help="可选运行统计文件")
    args = parser.parse_args()
    if not 30 <= args.time_limit <= 2280:
        parser.error("时限必须在 30 到 2280 秒之间")

    start = monotonic()
    deadline = start + args.time_limit
    processor, translator = load_translator(args.translation_model)
    prompt = SPAN_PROMPT.read_text(encoding="utf-8")
    support = SUPPORT_PROMPT.read_text(encoding="utf-8")
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    identity = {"model": args.model, "prompt_sha256": prompt_sha, "batch_size": args.batch_size}
    reviews, _ = load_reviews()
    groups = defaultdict(list)
    for review in reviews:
        if is_informative(review.text) and source_spans(review.text):
            groups[review.text].append(review)
    representatives = [group[0] for group in groups.values()]
    stats = Counter(eligible_reviews=sum(map(len, groups.values())), eligible_unique=len(groups))
    reserve = min(165, args.time_limit // 5)
    verify_reserve = min(650, args.time_limit // 4)
    selections = classify_reviews(args, prompt, identity, representatives, deadline - reserve - verify_reserve, stats)
    stats["classified_unique"] = len(selections)
    stats["classify_seconds"] = round(monotonic() - start, 3)

    classified = {}
    for review in representatives:
        if entry := selections.get(review.review_id):
            sentiment, issues = decode_selection(entry[1], review.text, source_spans(review.text))
            classified[review.text] = (sentiment, issues)
    verify_stats = Counter()
    verify_start = monotonic()
    verified = verify_evidence(args, support, classified, deadline - reserve, verify_stats)
    stats.update({f"verify_{name}": value for name, value in verify_stats.items()})
    stats["verify_seconds"] = round(monotonic() - verify_start, 3)
    quotes = {issue["evidence_quote"] for _, issues in verified.values() for issue in issues}
    translate_start = monotonic()
    translations = translate_quotes(quotes, processor, translator, deadline - 12, stats)
    stats["translate_seconds"] = round(monotonic() - translate_start, 3)
    stats["unique_quotes_to_translate"] = len(quotes)
    stats["unique_quotes_translated"] = len(translations)

    predictions = {}
    for source, (sentiment, selected) in verified.items():
        issues = [
            {**issue, "evidence_quote_en": translations[issue["evidence_quote"]]}
            for issue in selected if issue["evidence_quote"] in translations
        ]
        if selected and not issues:
            continue
        result = {
            "issues": issues, "sentiment_score": sentiment,
            "actionable_for_seller": any(issue["category"] in SELLER_ACTIONS for issue in issues),
            "confidence": 0.72 if issues else 0.60,
        }
        for review in groups[source]:
            predictions[review.review_id] = {
                "input_sha256": review.fingerprint(), "result": verify_prediction(result, review),
            }
    if not predictions:
        raise RuntimeError("未产生可用的评价缓存")
    # 每个 ID 独占一行，方便查看版本差异。
    entries = ",\n".join(
        "    " + json.dumps(review_id) + ": " + json.dumps(predictions[review_id], ensure_ascii=False, allow_nan=False)
        for review_id in sorted(predictions)
    )
    header = json.dumps({**identity, "prompt_sha256": span_prompt_digest(prompt, support)}, ensure_ascii=False)[:-1]
    write_text_atomic(SPAN_CACHE, header + ', "predictions": {\n' + entries + "\n  }\n}\n")
    stats["cache_reviews"] = len(predictions)
    stats["elapsed_seconds"] = round(monotonic() - start, 3)
    if args.stats_json:
        write_text_atomic(args.stats_json, json.dumps(stats, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
