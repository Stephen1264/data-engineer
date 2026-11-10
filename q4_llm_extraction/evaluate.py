"""全量校验证据，并计算开发样本和留出样本的类别指标。"""

import json
from collections import Counter

from q4_llm_extraction.extract_reviews import HERE, OUTPUT, load_reviews, write_text_atomic
from q4_llm_extraction.review_rules import CATEGORIES, SELLER_ACTIONS, SEVERITIES, quote_is_safe


def compare(actual: set, expected: set) -> Counter:
    assert expected <= set(CATEGORIES), expected
    return Counter(
        samples=1, exact=int(actual == expected),
        tp=len(actual & expected), fp=len(actual - expected), fn=len(expected - actual),
    )


def describe(counts: Counter) -> str:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0
    incorrect = fp / (tp + fp) if tp + fp else 0
    return (
        f"逐条类别集合完全一致 **{counts['exact']}/{counts['samples']}**。"
        f"类别微平均精确率 **{precision:.1%}**，召回率 **{recall:.1%}**，F1 **{f1:.1%}**。"
        f"TP {tp}，FP {fp}，FN {fn}。预测类别中标注未支持的比例 **{incorrect:.1%}**。"
    )


def main() -> None:
    reviews, _ = load_reviews()
    texts = {review.review_id: review.text for review in reviews}
    results = json.loads(OUTPUT.read_text(encoding="utf-8"))
    predictions = {}
    evidence = 0
    for row in results:
        assert set(row) == {"review_id", "issues", "sentiment_score", "actionable_for_seller", "confidence"}
        review_id = row["review_id"]
        assert review_id in texts and review_id not in predictions, review_id
        assert type(row["actionable_for_seller"]) is bool and isinstance(row["issues"], list)
        for field, lower, upper in (("sentiment_score", -1, 1), ("confidence", 0, 1)):
            assert type(row[field]) in {float, int} and lower <= row[field] <= upper, (review_id, field)
        categories = set()
        for issue in row["issues"]:
            assert set(issue) == {"category", "severity", "evidence_quote", "evidence_quote_en"}
            assert issue["category"] in CATEGORIES and issue["severity"] in SEVERITIES, review_id
            assert issue["category"] not in categories, review_id
            assert quote_is_safe(issue["evidence_quote"], texts[review_id]), review_id
            assert isinstance(issue["evidence_quote_en"], str) and issue["evidence_quote_en"].strip(), review_id
            categories.add(issue["category"])
            evidence += 1
        assert row["actionable_for_seller"] == bool(categories & SELLER_ACTIONS), review_id
        assert texts[review_id] or not categories, review_id
        predictions[review_id] = categories
    assert predictions.keys() == texts.keys(), "输出评论集合与输入不一致"

    labels = json.loads((HERE / "evaluation_labels.json").read_text(encoding="utf-8"))
    holdout = json.loads((HERE / "evaluation_holdout.json").read_text(encoding="utf-8"))
    development_ids = {row[0] for row in labels}
    holdout_ids = {row[0] for row in holdout}
    assert len(labels) == len(development_ids) == len(holdout) == len(holdout_ids) == 30
    assert development_ids.isdisjoint(holdout_ids), "开发样本与留出样本重叠"
    counts = Counter()
    by_stratum = {}
    differences = []
    for review_id, stratum, categories in labels:
        expected = set(categories)
        actual = predictions[review_id]
        entry = compare(actual, expected)
        counts.update(entry)
        by_stratum.setdefault(stratum, Counter()).update(entry)
        if actual != expected:
            differences.append((review_id, stratum, sorted(expected - actual), sorted(actual - expected)))

    holdout_counts = Counter()
    for review_id, categories in holdout:
        assert texts[review_id], review_id
        holdout_counts.update(compare(predictions[review_id], set(categories)))
    lines = [
        "# Q4 抽取准确率评估", "",
        "评估标签由 Codex 直接阅读葡语原文预标。正式评估需要葡语双人独立标注并仲裁分歧。"
        "两个样本各 30 条，标签与发布结果可独立重算。",
        "",
        "标注区分整单未收、部分缺件、送达超期和地址投递异常。正文只有情绪、正面送达评价或仍在等回复但无失联证据时，"
        "不推断具体问题。每个类别在同一评价最多计一次。", "",
        f"全量 **{len(results):,}** 条的结构、ID 覆盖和数值范围均通过检查。"
        f"发布的 **{evidence:,}** 条证据均是对应葡语正文的连续子串，且通过隐私模式筛查。"
        "原文可定位性与语义正确性分开计，后者还需要复核类别、严重度和翻译。",
        "", "## 开发样本与迭代", "",
        "初版固定种子 42，按空文本、短文本未命中、规则命中、模型入选、未入选复杂五层各抽 5、5、7、8、5 条。"
        "初版微平均 F1 为 52.4%。查看分歧后增加短句未送达、部分缺件和错误型号的保守规则。"
        "下面是同一样本的回归结果，反映修复覆盖。", "",
        describe(counts),
        "", "| 分层 | 样本 | 集合全对 | TP | FP | FN |", "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for stratum, entry in by_stratum.items():
        lines.append(
            f"| {stratum} | {entry['samples']} | {entry['exact']} | {entry['tp']} | {entry['fp']} | {entry['fn']} |"
        )
    lines.extend([
        "", "## 不一致的样本", "",
        "| 评价 ID | 分层 | 漏报类别 | 多报类别 |", "| --- | --- | --- | --- |",
    ])
    for review_id, stratum, missed, extra in differences:
        lines.append(f"| `{review_id}` | {stratum} | {', '.join(missed) or '—'} | {', '.join(extra) or '—'} |")
    lines.extend([
        "", "## 独立留出样本", "",
        "规则封版后，从未参与调整的有正文评价中以种子 613 随机抽取 30 条，"
        "先读正文确定参考类别，再对照发布结果。此样本只覆盖非空正文。", "",
        describe(holdout_counts), "",
        "较少见的拼写、替换词及隐含的数量和规格差异仍会漏报。复杂评论中，"
        "定位到原文的短引也可能不足以区分整单未收和部分缺件。线上应显示待复核状态，并优先补充这两个切片的标注。", "",
    ])
    write_text_atomic(HERE / "accuracy_evaluation.md", "\n".join(lines))
    print("Q4 全量证据检查通过，已生成开发和留出样本准确率报告")


if __name__ == "__main__":
    main()
