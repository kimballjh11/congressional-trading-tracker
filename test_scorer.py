# test_scorer.py — Unit tests for scorer.py's contrarian-buy signal
#
# Bug fixed: score_contrarian() passed `end = tx_date - timedelta(days=1)` to
# yfinance's Ticker.history(). yfinance's `end` parameter is EXCLUSIVE, so the
# intended "day before the purchase" was never actually the boundary used —
# the fetched window silently dropped the most recent trading day before the
# transaction, using a stale `price_end` for the contrarian-drop calculation.
# The fix passes `end = tx_date` instead (still exclusive, but now correctly
# includes the last trading day strictly before tx_date).

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime
import pandas as pd

import scorer


def make_trade(ticker="ACME", tx_type="Purchase", tx_date="06/16/2026"):
    return {
        "ticker": ticker,
        "transaction_type": tx_type,
        "transaction_date": tx_date,
    }


class TestContrarianEndDateBoundary(unittest.TestCase):
    """Confirms the `end` date passed to yfinance is the boundary date itself,
    not one day earlier (which would double-exclude given yfinance's
    exclusive-end semantics)."""

    def test_end_date_passed_to_yfinance_is_transaction_date(self):
        trade = make_trade(tx_date="06/16/2026")

        mock_hist = pd.DataFrame({"Close": [100.0] * 6})
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist

        with patch.object(scorer, "yf", MagicMock(Ticker=MagicMock(return_value=mock_ticker))):
            scorer.score_contrarian(trade)

        _, kwargs = mock_ticker.history.call_args
        self.assertEqual(kwargs["end"], "2026-06-16")
        # start should still be lookback days before the transaction date, untouched
        self.assertEqual(kwargs["start"], "2026-05-12")

    def test_end_date_is_not_one_day_before_transaction(self):
        """Regression guard: the old buggy behavior passed end=06/15 for a
        06/16 transaction — make sure we don't regress to that."""
        trade = make_trade(tx_date="06/16/2026")

        mock_hist = pd.DataFrame({"Close": [100.0] * 6})
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist

        with patch.object(scorer, "yf", MagicMock(Ticker=MagicMock(return_value=mock_ticker))):
            scorer.score_contrarian(trade)

        _, kwargs = mock_ticker.history.call_args
        self.assertNotEqual(kwargs["end"], "2026-06-15")


class TestContrarianSignalBehavior(unittest.TestCase):
    """End-to-end behavior checks using mocked price history, unaffected by
    the boundary-date fix itself (these should pass both before and after)."""

    def _run_with_history(self, closes, trade=None):
        trade = trade or make_trade()
        mock_hist = pd.DataFrame({"Close": closes})
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist
        with patch.object(scorer, "yf", MagicMock(Ticker=MagicMock(return_value=mock_ticker))):
            return scorer.score_contrarian(trade)

    def test_no_ticker_returns_zero(self):
        pts, reason = scorer.score_contrarian(make_trade(ticker=""))
        self.assertEqual(pts, 0)
        self.assertEqual(reason, "")

    def test_not_a_purchase_returns_zero(self):
        pts, reason = scorer.score_contrarian(make_trade(tx_type="Sale"))
        self.assertEqual(pts, 0)
        self.assertEqual(reason, "")

    def test_missing_date_returns_zero(self):
        pts, reason = scorer.score_contrarian(make_trade(tx_date=""))
        self.assertEqual(pts, 0)
        self.assertEqual(reason, "")

    def test_too_few_history_rows_returns_zero(self):
        pts, reason = self._run_with_history([100.0, 99.0, 98.0])
        self.assertEqual(pts, 0)
        self.assertEqual(reason, "")

    def test_large_drop_triggers_signal(self):
        # 100 -> 85 is a 15% drop, past the -10% threshold
        pts, reason = self._run_with_history([100.0, 98.0, 95.0, 90.0, 85.0])
        self.assertEqual(pts, scorer.POINTS_CONTRARIAN_BUY)
        self.assertIn("Contrarian buy", reason)

    def test_small_drop_does_not_trigger_signal(self):
        # 100 -> 95 is only a 5% drop, under the -10% threshold
        pts, reason = self._run_with_history([100.0, 99.0, 98.0, 97.0, 95.0])
        self.assertEqual(pts, 0)
        self.assertIn("no signal", reason)


class TestContrarianRealisticRegression(unittest.TestCase):
    """Reproduces the concrete scenario found via live yfinance data
    (AAPL/MSFT around a Tuesday transaction date): the trading day
    immediately preceding the purchase carries a materially different
    closing price than the one two trading days prior. Confirms the fixed
    boundary actually changes which price is used as `price_end`."""

    def test_fix_uses_the_last_pre_purchase_trading_day(self):
        trade = make_trade(tx_date="06/16/2026")

        # Simulate yfinance returning different windows depending on the
        # `end` boundary passed in — mirrors real observed behavior where
        # end=06/15 (the buggy value) omits the 06/15 trading day itself.
        def fake_history(start, end):
            full_index = pd.to_datetime(
                ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11",
                 "2026-06-12", "2026-06-15", "2026-06-16"]
            )
            # A sharp drop by 06/12, fully recovered by 06/15 (the trading
            # day immediately before the 06/16 purchase).
            full_closes = [100.0, 97.0, 95.0, 90.0, 80.0, 100.0, 101.0]
            df = pd.DataFrame({"Close": full_closes}, index=full_index)
            return df[df.index < pd.Timestamp(end)]

        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = fake_history

        with patch.object(scorer, "yf", MagicMock(Ticker=MagicMock(return_value=mock_ticker))):
            with patch.object(scorer, "CONTRARIAN_LOOKBACK_DAYS", 10):
                pts, reason = scorer.score_contrarian(trade)

        # With the fix (end=06/16, exclusive), the window includes 06/15
        # (close=100.0, fully recovered) as price_end — no drop, no signal.
        # The pre-fix code (end=06/15, exclusive) would have excluded 06/15
        # entirely and used the still-depressed 06/12 close (80.0) as
        # price_end, incorrectly firing the contrarian signal.
        self.assertEqual(pts, 0)
        self.assertIn("no signal", reason)


if __name__ == "__main__":
    unittest.main()
