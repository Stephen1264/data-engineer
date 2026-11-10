"""全量校验证据，并计算开发样本和留出样本的类别指标。"""

import json
from collections import Counter

from q4_llm_extraction.extract_reviews import HERE, OUTPUT, load_reviews, write_text_atomic
from q4_llm_extraction.review_rules import CATEGORIES, PRIVATE_QUOTE, SELLER_ACTIONS, SEVERITIES, quote_is_safe


def compare(actual: set, expected: set) -> Counter:
    assert expected <= set(CATEGORIES), expected
    return Counter(
        samples=1, exact=int(actual == expected),
        tp=len(actual & expected), fp=len(actual - expected), fn=len(expected - actual),
    )


def metrics(counts: Counter) -> tuple[float, float, float]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0
    return precision, recall, f1


def describe(counts: Counter) -> str:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision, recall, f1 = metrics(counts)
    incorrect = fp / (tp + fp) if tp + fp else 0
    return (
        f"逐条类别集合完全一致 **{counts['exact']}/{counts['samples']}**。"
        f"类别微平均精确率 **{precision:.1%}**，召回率 **{recall:.1%}**，F1 **{f1:.1%}**。"
        f"TP {tp}，FP {fp}，FN {fn}。预测类别中标注未支持的比例 **{incorrect:.1%}**。"
    )


def compare_nonempty(labels_path, texts, predictions, used_ids: set) -> Counter:
    sample = json.loads(labels_path.read_text(encoding="utf-8"))
    ids = {row[0] for row in sample}
    assert len(sample) == len(ids) == 30 and used_ids.isdisjoint(ids), "样本规模或独立性错误"
    used_ids.update(ids)
    counts = Counter()
    for review_id, categories in sample:
        assert texts[review_id], review_id
        counts.update(compare(predictions[review_id], set(categories)))
    return counts


def release_comparison(texts, predictions, used_ids: set) -> list[str]:
    diagnostic = json.loads((HERE / "evaluation_v2_holdout.json").read_text(encoding="utf-8"))
    diagnostic_ids = {row[0] for row in diagnostic}
    assert len(diagnostic) == len(diagnostic_ids) == 60 and used_ids.isdisjoint(diagnostic_ids)
    used_ids.update(diagnostic_ids)
    diagnostic_counts = Counter()
    for review_id, expected, _ in diagnostic:
        assert texts[review_id], review_id
        diagnostic_counts.update(compare(predictions[review_id], set(expected)))

    sample = json.loads((HERE / "evaluation_v2_final.json").read_text(encoding="utf-8"))
    ids = {row[0] for row in sample}
    assert len(sample) == len(ids) == 40 and used_ids.isdisjoint(ids), "新版留出样本无效"
    versions = {"上一提交 c7d7b12": Counter(), "两轮模型，程序筛查前": Counter(), "最终版本": Counter()}
    by_category = {category: Counter() for category in CATEGORIES}
    for review_id, expected, baseline, draft in sample:
        assert texts[review_id] and set(baseline) <= set(CATEGORIES), review_id
        expected, actual = set(expected), predictions[review_id]
        versions["上一提交 c7d7b12"].update(compare(set(baseline), expected))
        versions["两轮模型，程序筛查前"].update(compare(set(draft), expected))
        versions["最终版本"].update(compare(actual, expected))
        correct, extra, missed = actual & expected, actual - expected, expected - actual
        for category in CATEGORIES:
            by_category[category].update(
                tp=int(category in correct), fp=int(category in extra), fn=int(category in missed),
            )
    lines = [
        "## 最终独立留出样本", "",
        "用固定种子 20261111 从有正文评价中随机抽取 40 条，排除已用的诊断、试跑和引文抽查样本。"
        "Codex 在查看这组样本的预测前逐条阅读葡语正文并锁定参考类别。"
        "基线取上一公开提交的输出，表中三组共用同一批评价与标注。"
        "样本量有限，标签尚未经过独立人工复标。", "",
        "| 版本 | 完全一致 | 类别精确率 | 类别召回率 | 类别 F1 | TP | FP | FN |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for version, counts in versions.items():
        precision, recall, f1 = metrics(counts)
        lines.append(
            f"| {version} | {counts['exact']}/{counts['samples']} | {precision:.1%} | {recall:.1%} | "
            f"{f1:.1%} | {counts['tp']} | {counts['fp']} | {counts['fn']} |"
        )
    lines.extend([
        "", "类别指标按样本中的每个评价与类别组合计算。部分缺件和整单未到区分处理。"
        "单说仍在运输且没有逾期或未收到的抱怨时，不标配送迟到。"
        "缺发票归为其他问题，规格差异归为发错商品。", "",
        "| 类别 | 当前 TP | 当前 FP | 当前 FN |", "| --- | ---: | ---: | ---: |",
    ])
    for category, counts in by_category.items():
        lines.append(f"| `{category}` | {counts['tp']} | {counts['fp']} | {counts['fn']} |")
    lines.extend([
        "", "原文引用可定位只说明证据来自对应评价。少见品类、隐含比较和投诉主体仍可能分错，"
        "严重度及译文也需要抽样复核。", "",
        "## 筛查前后的诊断对照", "",
        "种子 20261110 的 60 条样本在两轮模型初次运行时，精确率 66.7%，召回率 47.6%，F1 55.6%。"
        "抽查发现有些原文片段虽然真实，却缺少缺件、包装损坏等类别所需的证据。"
        "因此新增类别相关的证据线索筛查，并补充未收到、未获回复和缺发票等常见写法。"
        "以下为同一批 60 条在最终版本上的诊断结果。", "",
        describe(diagnostic_counts), "",
    ])
    return lines


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
            translation = issue["evidence_quote_en"]
            assert isinstance(translation, str) and 1 <= len(translation.strip()) <= 360, review_id
            assert not PRIVATE_QUOTE.search(translation), review_id
            categories.add(issue["category"])
            evidence += 1
        assert row["actionable_for_seller"] == bool(categories & SELLER_ACTIONS), review_id
        assert texts[review_id] or not categories, review_id
        predictions[review_id] = categories
    assert predictions.keys() == texts.keys(), "输出评论集合与输入不一致"

    labels = json.loads((HERE / "evaluation_labels.json").read_text(encoding="utf-8"))
    development_ids = {row[0] for row in labels}
    assert len(labels) == len(development_ids) == 30
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

    diagnostic_counts = compare_nonempty(HERE / "evaluation_holdout.json", texts, predictions, development_ids)
    holdout_counts = compare_nonempty(HERE / "evaluation_final_sample.json", texts, predictions, development_ids)
    lines = [
        "# Q4 抽取准确率评估", "",
        "评估标签由 Codex 直接阅读葡语原文预标。正式评估需要葡语双人独立标注并仲裁分歧。"
        "前三批各有 30 条，改版另外使用 60 条做诊断及 40 条做最终留出比较。",
        "",
        "标注区分整单未收、部分缺件、送达超期和地址投递异常。正文只有情绪、正面送达评价或仍在等回复但无失联证据时，"
        "不推断具体问题。每个类别在同一评价最多计一次。", "",
        f"全量 **{len(results):,}** 条的结构、ID 覆盖和数值范围均通过检查。"
        f"发布的 **{evidence:,}** 条证据均是对应葡语正文的连续子串，且通过隐私模式筛查。"
        "原文可定位性与语义正确性分开计，后者还需要复核类别、严重度和翻译。",
        "", *release_comparison(texts, predictions, development_ids),
        "## 开发样本与迭代", "",
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
        "", "## 第二批诊断样本", "",
        "用种子 613 抽取非空正文，第一次对照的微平均 F1 为 15.8%。"
        "检查漏报后补充未发货、损坏配件及投递异常等证据，并区分部分缺件和整单未收到。"
        "以下仍是诊断样本的回归结果。", "",
        describe(diagnostic_counts),
        "", "## 旧留出样本回归", "",
        "上一版的种子 2401 样本在本轮用于排查误报和比较复核策略。"
        "本轮的独立对照见前面的 40 条样本。", "",
        describe(holdout_counts), "",
        "如用于线上决策，可先补充低频类别和跨句证据的人工标注，"
        "并继续核对空问题输出中的漏报。", "",
    ])
    write_text_atomic(HERE / "accuracy_evaluation.md", "\n".join(lines))
    print("Q4 全量证据检查通过，已生成开发和留出样本准确率报告")


if __name__ == "__main__":
    main()
