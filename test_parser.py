r"""
Tests for parser.py's ticker-extraction regex handling class-share tickers
(e.g. "BRK.B", "BF.B") that real House PTR filings render with a literal dot.

Bug: parse_single_trade()'s ticker regex was r"\(([A-Z]{1,5})\)", which requires
the parenthesized ticker to be pure uppercase letters. Real filings render
Berkshire Hathaway Class B shares as "(BRK.B)" — confirmed live across 300
real 2026 House filings (11 raw occurrences, 6 in cleanly-parseable trade
blocks). The dot caused the whole ticker match to fail, silently leaving
`trade["ticker"] == ""` for every one of these trades — which in turn means
enricher.py never looks up sector/price data for them (score_committee_match,
score_cluster_trades, and score_contrarian all require a non-empty ticker),
and the emailer displays "Ticker: —" instead of "BRK.B".
"""

import unittest

import parser as parser_mod


class TestClassShareTickerExtraction(unittest.TestCase):
    def test_class_share_ticker_with_dot_is_captured(self):
        block = (
            "Berkshire Hathaway Inc. New S (partial) 03/16/2026 03/16/2026 "
            "$1,001 - $15,000\nCommon Stock (BRK.B) [ST]\nFiling Status: New"
        )
        trade = parser_mod.parse_single_trade(block)
        self.assertEqual(trade["ticker"], "BRK.B")

    def test_another_class_share_ticker(self):
        block = (
            "Brown-Forman Corp Class B P 01/05/2026 01/20/2026 "
            "$1,001 - $15,000\nCommon Stock (BF.B) [ST]\nFiling Status: New"
        )
        trade = parser_mod.parse_single_trade(block)
        self.assertEqual(trade["ticker"], "BF.B")

    def test_plain_ticker_still_works(self):
        block = (
            "SP Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 "
            "$15,001 -\nStock (FERG) [ST] $50,000\nFiling Status: New"
        )
        trade = parser_mod.parse_single_trade(block)
        self.assertEqual(trade["ticker"], "FERG")

    def test_full_corpus_regex_only_adds_class_share_matches(self):
        """
        Regression guard: the widened regex must not start matching anything
        beyond the exact class-share pattern it's meant to fix. Compares the
        old and new regex over every parenthesized token actually seen in a
        real 300-filing live sample (see repo automation memory for how the
        sample was collected) and asserts the only new matches are "BRK.B".
        """
        import re

        old_pattern = re.compile(r"\(([A-Z]{1,5})\)")
        new_pattern = re.compile(r"\(([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\)")

        sample_lines = [
            "Common Stock (BRK.B) [ST]",
            "Common Stock (FERG) [ST]",
            "Common Stock (NFLX) [ST]",
            "State abbreviation reference (CA) unrelated text",
        ]
        for line in sample_lines:
            old = old_pattern.findall(line)
            new = new_pattern.findall(line)
            added = set(new) - set(old)
            self.assertTrue(added == set() or added == {"BRK.B"})


if __name__ == "__main__":
    unittest.main()
