# test_scorer.py — Regression tests for scorer.py's disclosure-delay signal
#
# Background: score_disclosure_delay() only awarded points for delays of
# 30-45 days. Real House PTR filings can be disclosed well past the STOCK
# Act's 45-day legal deadline (confirmed live, e.g. a genuine Tim Walberg
# filing with a 476-day delay) — those trades scored 0 points on this
# signal even though a confirmed violation of the disclosure deadline is
# at least as suspicious as merely being close to it.

import unittest

from scorer import score_disclosure_delay
from config import POINTS_DELAY_NEAR_LIMIT, POINTS_DELAY_LATE

try:
    from config import POINTS_DELAY_VIOLATION
except ImportError:
    POINTS_DELAY_VIOLATION = None  # not yet defined on unpatched code


def make_trade(transaction_date, notification_date):
    return {
        "transaction_date": transaction_date,
        "notification_date": notification_date,
    }


class TestDisclosureDelayScoring(unittest.TestCase):
    def test_over_45_days_is_a_violation(self):
        # Real filing: transaction 02/07/2025, notification 05/29/2026 (476 days)
        trade = make_trade("02/07/2025", "05/29/2026")
        pts, reason = score_disclosure_delay(trade)
        self.assertGreater(pts, 0, "a 476-day-late disclosure should not score 0")
        self.assertEqual(pts, POINTS_DELAY_VIOLATION)
        self.assertIn("476", reason)
        self.assertIn("violation", reason.lower())

    def test_exactly_46_days_is_a_violation(self):
        trade = make_trade("01/01/2026", "02/16/2026")  # 46 days
        pts, reason = score_disclosure_delay(trade)
        self.assertGreater(pts, 0, "a 46-day-late disclosure should not score 0")
        self.assertEqual(pts, POINTS_DELAY_VIOLATION)

    def test_near_limit_38_to_45_days_unaffected(self):
        trade = make_trade("01/01/2026", "02/15/2026")  # 45 days
        pts, reason = score_disclosure_delay(trade)
        self.assertEqual(pts, POINTS_DELAY_NEAR_LIMIT)

    def test_late_30_to_37_days_unaffected(self):
        trade = make_trade("01/01/2026", "01/31/2026")  # 30 days
        pts, reason = score_disclosure_delay(trade)
        self.assertEqual(pts, POINTS_DELAY_LATE)

    def test_within_normal_window_unaffected(self):
        trade = make_trade("01/01/2026", "01/10/2026")  # 9 days
        pts, reason = score_disclosure_delay(trade)
        self.assertEqual(pts, 0)

    def test_negative_delay_unaffected(self):
        # e.g. a bond maturity date mistakenly parsed as the transaction date
        trade = make_trade("12/30/2031", "12/05/2025")
        pts, reason = score_disclosure_delay(trade)
        self.assertEqual(pts, 0)

    def test_missing_dates_unaffected(self):
        pts, reason = score_disclosure_delay(make_trade("", ""))
        self.assertEqual(pts, 0)


if __name__ == "__main__":
    unittest.main()
