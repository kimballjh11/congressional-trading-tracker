# test_parser.py — Unit tests for parser.py's trade-block parsing
#
# Focus of this file: the ticker-extraction fallback for funds that render
# their ticker as "(Ticker: XXXXX)" instead of the usual bare "(XXXXX)".
# Run with: PYTHONPATH=/workspace python3 -m pytest test_parser.py -v

import unittest

from parser import parse_single_trade


class TestTickerExtraction(unittest.TestCase):
    def test_bare_parens_ticker_still_matches(self):
        block = (
            "Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 $15,001 -\n"
            "Stock (FERG) [ST] $50,000"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["ticker"], "FERG")

    def test_ticker_label_fallback_matches(self):
        # Real closed-end/mutual funds render their ticker as
        # "(Ticker: CCLFX)" instead of the usual bare "(CCLFX)".
        block = (
            "Steward Partners Small Cap Fund (Ticker: CCLFX) [MF] "
            "P 03/01/2026 03/25/2026 $1,001 - $15,000"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["ticker"], "CCLFX")

    def test_ticker_label_fallback_is_case_insensitive(self):
        block = (
            "Some Fund (ticker: abcde) [MF] "
            "P 03/01/2026 03/25/2026 $1,001 - $15,000"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["ticker"], "ABCDE")

    def test_bare_parens_preferred_when_both_could_apply(self):
        # If the block has a bare "(XXXX)" ticker, it should be used
        # directly without needing the "(Ticker: ...)" fallback.
        block = (
            "Netflix Inc Common Stock (NFLX) [ST] "
            "S 01/02/2026 01/20/2026 $50,001 - $100,000"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["ticker"], "NFLX")

    def test_no_ticker_present_leaves_empty(self):
        block = (
            "Some Municipal Bond 4.00% "
            "P 01/02/2026 01/20/2026 $50,001 - $100,000"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["ticker"], "")


if __name__ == "__main__":
    unittest.main()
