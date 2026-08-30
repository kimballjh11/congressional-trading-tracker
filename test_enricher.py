"""
Tests for enricher.py's yfinance ticker normalization.

Bug (paired with the parser.py class-share ticker fix in test_parser.py):
even once a class-share ticker like "BRK.B" is correctly extracted from a
filing, passing it straight to yfinance returns no data at all — yfinance
only recognizes the hyphenated form ("BRK-B"). Confirmed live:
  yf.Ticker("BRK.B").info -> sector None, shortName None
  yf.Ticker("BRK-B").info -> sector "Financial Services", shortName "Berkshire..."
fetch_stock_info() must convert the dot to a hyphen before calling yfinance,
while still keying trades/results by the original filed ticker ("BRK.B") so
cluster-trading and email display stay consistent with what's on the PTR.
"""

import unittest
from unittest import mock

import enricher


class TestYfinanceTickerNormalization(unittest.TestCase):
    def test_to_yfinance_symbol_converts_dot_to_hyphen(self):
        self.assertEqual(enricher.to_yfinance_symbol("BRK.B"), "BRK-B")
        self.assertEqual(enricher.to_yfinance_symbol("BF.B"), "BF-B")

    def test_to_yfinance_symbol_leaves_plain_tickers_unchanged(self):
        self.assertEqual(enricher.to_yfinance_symbol("NFLX"), "NFLX")
        self.assertEqual(enricher.to_yfinance_symbol(""), "")
        self.assertIsNone(enricher.to_yfinance_symbol(None))

    def test_fetch_stock_info_calls_yfinance_with_normalized_symbol(self):
        with mock.patch.object(enricher, "yf") as mock_yf:
            mock_ticker = mock.MagicMock()
            mock_ticker.info = {
                "currentPrice": 505.0,
                "sector": "Financial Services",
                "industry": "Insurance - Diversified",
            }
            mock_yf.Ticker.return_value = mock_ticker

            result = enricher.fetch_stock_info("BRK.B")

            mock_yf.Ticker.assert_called_once_with("BRK-B")
            self.assertEqual(result["sector"], "Financial Services")
            self.assertEqual(result["current_price"], 505.0)


if __name__ == "__main__":
    unittest.main()
