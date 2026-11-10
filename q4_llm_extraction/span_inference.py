"""用本地模型定位问题，不让模型重写证据。"""

import json
import re

from q4_llm_extraction.review_rules import quote_is_safe

CODES = {
    "L": "delivery_late", "W": "wrong_product", "D": "quality_defect", "M": "missing_item",
    "C": "seller_communication", "P": "packaging", "O": "other",
}
SENTIMENTS = {"N": -0.7, "U": 0.0, "P": 0.6}
SEVERITY = {"1": "low", "2": "medium", "3": "high"}
BOUNDARY = re.compile(r"(?<=[.!?;])\s+|[\r\n]+")
GENERIC = re.compile(
    r"(?:muito )?(?:ruim|p[ée]ssim[oa]|regular|bom|boa|[óo]tim[oa]|excelente|"
    r"gostei|n[ãa]o gostei|recomendo|n[ãa]o recomendo|legal|ok)", re.IGNORECASE,
)
LINE = re.compile(r"[NUP] (?:0|[LWDMCPO][1-8][1-8][1-3](?: [LWDMCPO][1-8][1-8][1-3]){0,3})")


def source_spans(text: str) -> list[tuple[int, int]]:
    """保留原字符位置，让两段之间的标点和空白也可追溯。"""
    spans = []
    start = 0
    for end in [*(match.end() for match in BOUNDARY.finditer(text)), len(text)]:
        while start < end:
            if text[start].isspace():
                start += 1
                continue
            stop = min(start + 180, end)
            if stop < end:
                cut = text.rfind(" ", start + 3, stop)
                if cut >= 0:
                    stop = cut
            quote_end = start + len(text[start:stop].rstrip())
            if quote_end - start >= 3:
                spans.append((start, quote_end))
            start = stop
    return spans[:8]


def is_informative(text: str) -> bool:
    trimmed = text.strip(" .,!?:;\n\r\t")
    return bool(trimmed and any(char.isalpha() for char in trimmed) and not GENERIC.fullmatch(trimmed))


def local_payload(prompt: str, source, grammar: str, token_limit: int) -> dict:
    source = json.dumps(source, ensure_ascii=False).replace("<", "\\u003c")
    chat = (
        f"<|im_start|>system\n{prompt.strip()}<|im_end|>\n"
        f"<|im_start|>user\n{source}<|im_end|>\n<|im_start|>assistant\n"
    )
    return {
        "prompt": chat, "grammar": grammar, "temperature": 0, "seed": 42,
        "n_predict": token_limit, "cache_prompt": True,
    }


def request_payload(prompt: str, items: list[tuple[str, list[tuple[int, int]]]]) -> dict:
    excerpts = [
        [f"{index}: {text[start:end]}" for index, (start, end) in enumerate(spans, 1)]
        for text, spans in items
    ]
    rows = [f"row-{number}" for number in range(len(items))]
    rules = ['root ::= ' + r' "\n" '.join(rows)]
    for number, (_, spans) in enumerate(items):
        index = '"1"' if len(spans) == 1 else f"[1-{len(spans)}]"
        issue = f"issue-{number}"
        rules.append(f'{rows[number]} ::= [NUP] " " ("0" | {issue} (" " {issue}){{0,3}})')
        rules.append(f"{issue} ::= [LWDMCPO] {index} {index} [1-3]")
    return local_payload(prompt, excerpts, "\n".join(rules), 30 * len(items))


def support_payload(prompt: str, items: list[tuple[str, list[dict]]]) -> dict:
    codes = {category: code for code, category in CODES.items()}
    source = [
        {"text": text, "checks": [[codes[issue["category"]], issue["evidence_quote"]] for issue in issues]}
        for text, issues in items
    ]
    grammar = 'root ::= ' + r' "\n" '.join(f"[01]{{{len(issues)}}}" for _, issues in items)
    return local_payload(prompt, source, grammar, 10 * len(items))


def supported_issues(bits: str, issues: list[dict]) -> list[dict]:
    if len(bits) != len(issues) or set(bits) - {"0", "1"}:
        raise ValueError("证据复核结果与提案数量不一致")
    return [issue for bit, issue in zip(bits, issues) if bit == "1"]


def decode_selection(content: str, text: str, spans: list[tuple[int, int]]) -> tuple[float, list[dict]]:
    """按类别保留第一条合法原文，错误范围不影响其它类别。"""
    content = content.strip()
    if not LINE.fullmatch(content):
        raise ValueError("模型输出未完成或不符合编号格式")
    sentiment, *codes = content.split()
    issues = {}
    for code in codes:
        if code == "0":
            continue
        category = CODES[code[0]]
        first, last = int(code[1]), int(code[2])
        if not 1 <= first <= last <= len(spans) or category in issues:
            continue
        quote = text[spans[first - 1][0]:spans[last - 1][1]]
        if quote_is_safe(quote, text):
            issues[category] = {
                "category": category, "severity": SEVERITY[code[3]], "evidence_quote": quote,
            }
    return SENTIMENTS[sentiment], list(issues.values())
