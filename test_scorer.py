"""
Test for scorer.py's score_contrarian() applying the same class-share ticker
normalization as enricher.py (see test_enricher.py) — yfinance needs "BRK-B",
not the filed "BRK.B", or Ticker.history() silently returns no rows.
"""

import unittest
from unittest import mock
from datetime import datetime, timedelta

import scorer


class TestContrarianClassShareTicker(unittest.TestCase):
    def test_score_contrarian_calls_yfinance_with_normalized_symbol(self):
        tx_date = datetime.now() - timedelta(days=5)
        trade = {
            "ticker": "BRK.B",
            "transaction_type": "Purchase",
            "transaction_date": tx_date.strftime("%m/%d/%Y"),
        }

        with mock.patch.object(scorer, "yf") as mock_yf:
            mock_stock = mock.MagicMock()
            mock_hist = mock.MagicMock()
            mock_hist.empty = True
            mock_stock.history.return_value = mock_hist
            mock_yf.Ticker.return_value = mock_stock

            scorer.score_contrarian(trade)

            mock_yf.Ticker.assert_called_once_with("BRK-B")


if __name__ == "__main__":
    unittest.main()
