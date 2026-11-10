"""回归核对取消的时间边界和评价证据。"""

import unittest

import pandas as pd

from q3_etl_pipeline.pipeline import compute_rfm, filter_real_sales, match_returns
from q4_llm_extraction.extract_reviews import Review, verify_prediction
from q4_llm_extraction.review_rules import detect_issues


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
