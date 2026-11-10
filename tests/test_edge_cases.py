"""回归核对取消的时间边界和评价证据。"""

import unittest
from time import monotonic
from unittest.mock import patch

import pandas as pd

from q3_etl_pipeline.pipeline import compute_rfm, filter_real_sales, match_returns
from q4_llm_extraction.extract_reviews import Review, merge_result, verify_prediction
from q4_llm_extraction.evidence_guard import ground_issue, supports_category
from q4_llm_extraction.review_rules import detect_issues
from q4_llm_extraction.build_span_cache import classify_packet
from q4_llm_extraction.span_inference import decode_selection, source_spans, supported_issues


class ReturnsTests(unittest.TestCase):
    def test_strict_time_single_use_and_partial_return(self):
        entries = [
            ("100", 5, "08:00"), ("101", 5, "09:00"), ("102", 5, "09:00"),
            ("C103", -5, "09:00"), ("C104", -5, "10:00"), ("C105", -5, "11:00"),
            ("C106", -5, "12:00"), ("107", 10, "12:00"), ("C108", -4, "13:00"),
        ]
        frame = pd.DataFrame(entries, columns=["invoice_no", "quantity", "time"])
        frame["invoice_datetime"] = pd.to_datetime("2011-01-01 " + frame.pop("time"))
        frame["description"] = "样例"
        frame["stock_code"] = "12345"
        frame["country"] = "United Kingdom"
        frame["customer_id"] = "123"
        for column in ("invoice_no", "stock_code", "country", "customer_id", "description"):
            frame[column] = frame[column].astype("string")
        frame["unit_price"] = 2.0
        frame["total_amount"] = frame["quantity"] * frame["unit_price"]
        sales = filter_real_sales(frame)
        returns, _, stats = match_returns(frame, sales)
        matches = returns.set_index("invoice_no")["matched_original_invoice"].to_dict()
        self.assertEqual([matches[key] for key in ("C103", "C104", "C105")], ["100", "102", "101"])
        self.assertTrue(pd.isna(matches["C106"]))
        self.assertTrue(pd.isna(matches["C108"]))
        self.assertEqual(stats["consumed"], 1)
        features = compute_rfm(sales, pd.Timestamp("2011-01-03"))
        self.assertEqual(features["frequency"].iloc[0], 4)
        self.assertEqual(features["recency_days"].iloc[0], 2)


class ReviewTests(unittest.TestCase):
    def test_short_generic_and_negation(self):
        self.assertEqual(detect_issues("Ruim"), [])
        self.assertEqual(detect_issues("O produto não veio quebrado."), [])
        issues = detect_issues("O produto veio quebrado e a caixa estava amassada.")
        self.assertEqual({x["category"] for x in issues}, {"quality_defect", "packaging"})

    def test_reject_fabricated_evidence(self):
        review = Review("sample", 1, "Produto chegou quebrado")
        result = {
            "issues": [{
                "category": "delivery_late", "severity": "high",
                "evidence_quote": "entrega atrasada", "evidence_quote_en": "late delivery",
            }],
            "sentiment_score": -1.0, "actionable_for_seller": False, "confidence": 0.8,
        }
        with self.assertRaises(ValueError):
            verify_prediction(result, review)

    def test_partial_delivery_and_explicit_lateness(self):
        for sentence, categories in (
            ("O produto não foi entregue.", {"missing_item"}),
            ("A entrega atrasou.", {"missing_item", "delivery_late"}),
        ):
            review = Review("sample", 1, "Recebi somente 1 item. " + sentence)
            result, _ = merge_result(review, detect_issues(review.text), None)
            self.assertEqual({issue["category"] for issue in result["issues"]}, categories)

    def test_span_range_keeps_both_quantity_statements(self):
        source = "Comprei DUAS unidades.\r\nSó veio uma."
        sentiment, issues = decode_selection("N M123", source, source_spans(source))
        self.assertLess(sentiment, 0)
        self.assertEqual(issues, [{
            "category": "missing_item", "severity": "high", "evidence_quote": source,
        }])
        self.assertEqual(supported_issues("0", issues), [])
        with self.assertRaises(ValueError):
            supported_issues("10", issues)

    def test_explicit_late_evidence_survives_partial_delivery_merge(self):
        quote = "Não recebi o produto no prazo."
        review = Review("sample", 1, "Recebi somente 1 item. " + quote)
        prediction = {
            "issues": [{
                "category": "delivery_late", "severity": "medium",
                "evidence_quote": quote, "evidence_quote_en": "I did not receive the product on time.",
            }],
            "sentiment_score": -0.7, "actionable_for_seller": False, "confidence": 0.72,
        }
        result, _ = merge_result(review, detect_issues(review.text), prediction)
        self.assertEqual({issue["category"]: issue["evidence_quote"] for issue in result["issues"]}, {
            "missing_item": "Recebi somente 1 item", "delivery_late": quote,
        })

    def test_span_rejects_reversed_range_and_private_quote(self):
        source = "Meu CPF é 123.456.789-12. O aparelho não liga."
        _, issues = decode_selection("N C111 L211 D222", source, source_spans(source))
        self.assertEqual([issue["evidence_quote"] for issue in issues], ["O aparelho não liga."])

    def test_truncated_packet_cannot_shift_predictions_between_reviews(self):
        reviews = [Review("a", 1, "A entrega atrasou."), Review("b", 2, "O produto veio quebrado.")]
        with patch("q4_llm_extraction.build_span_cache.call_local_llm", return_value={"content": "N L112"}):
            selected, stats = classify_packet("http://localhost", "prompt", reviews, monotonic() + 10)
        self.assertEqual(selected, [])
        self.assertEqual(stats["failed_packets"], 1)

    def test_category_guard_requires_specific_claim_in_quote(self):
        for category, quote, expected in (
            ("missing_item", "Comprei 05 unidades do produto.", False),
            ("missing_item", "Comprei dois livros e recebi somente 1.", True),
            ("missing_item", "O pacote chegou só um dia depois.", False),
            ("delivery_late", "Ainda não mandaram todos os produtos!", False),
            ("delivery_late", "O produto não foi entregue dentro do prazo.", True),
            ("seller_communication", "Gostaria de um retorno, pois já paguei.", False),
            ("seller_communication", "Escrevi para a loja e ninguém me respondeu.", True),
            ("packaging", "Abri a caixa e veio um modelo errado.", False),
            ("packaging", "A caixa chegou toda amassada.", True),
        ):
            with self.subTest(category=category, quote=quote):
                self.assertEqual(supports_category(category, quote), expected)
        issue = {
            "category": "delivery_late", "severity": "high",
            "evidence_quote": "Chegou um dos produtos, porém o outro não chegou.",
            "evidence_quote_en": "One of the products arrived, but the other did not.",
        }
        self.assertEqual(ground_issue(issue), {**issue, "category": "missing_item"})
