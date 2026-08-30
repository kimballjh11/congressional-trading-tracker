# test_parser.py — Regression tests for parser.py's trade-detail extraction.

import unittest

from parser import parse_single_trade


class TestSpouseDependentOverBracket(unittest.TestCase):
    """
    Spouse/dependent-child trades have their own top amount bracket: an
    open-ended "Over $1,000,000" (no upper bound), distinct from the filer's
    own graduated brackets. Real House PTR PDFs render this as
    "Spouse/DC Over\n[GS] $1,000,000" or "[GS] Spouse/DC Over\n$1,000,000"
    depending on layout — either way, only a single dollar figure appears in
    the extracted text. Treating that lone figure as an exact amount instead
    of an open-ended floor is misleading, since real trades in this bracket
    can be tens of millions of dollars.
    """

    def test_over_bracket_with_asset_code_before_amount(self):
        block = (
            "SP U.S. Treasury Note due 2/28/2029 P 12/15/2025 12/16/2025 "
            "Spouse/DC Over\n[GS] $1,000,000\nFiling Status: New"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["amount"], "Over $1,000,000")

    def test_over_bracket_with_asset_code_after_over(self):
        block = (
            "SP Riverside CA Elec Util [GS] S 03/30/2026 03/31/2026 "
            "Spouse/DC Over\n$1,000,000\nFiling Status: New"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["amount"], "Over $1,000,000")

    def test_normal_range_amount_unaffected(self):
        block = (
            "SP Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 "
            "$15,001 -\nStock (FERG) [ST] $50,000\nFiling Status: New"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["amount"], "$15,001 - $50,000")

    def test_single_exact_amount_without_over_keyword_unaffected(self):
        # Some real trades (e.g. IRA sales) report a single exact dollar
        # figure rather than a range or an "Over" bracket — that figure
        # should be left as-is, not mistaken for the Spouse/DC bracket.
        block = (
            "Ichor Holdings - Ordinary Shares S 06/17/2026 07/14/2026 "
            "$2,722.50\n(ICHR) [ST]\nFiling Status: New\n"
            "Description: Sale from Individual Retirement Account"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["amount"], "$2,722")

    def test_over_keyword_far_from_amount_does_not_false_positive(self):
        # An unrelated use of the word "over" elsewhere in the block (e.g. in
        # free-text description) should not trigger the Spouse/DC handling
        # for a normal, single, non-bracket dollar figure.
        block = (
            "Widget Corp Common Stock S 06/17/2026 07/14/2026 $2,722\n"
            "(WDGT) [ST]\nFiling Status: New\n"
            "Description: Shares rolled over from a prior account"
        )
        trade = parse_single_trade(block)
        self.assertEqual(trade["amount"], "$2,722")


if __name__ == "__main__":
    unittest.main()
