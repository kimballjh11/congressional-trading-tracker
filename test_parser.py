# test_parser.py — Regression tests for parser.py's trade block-splitting.
#
# Context: split_trade blocks are detected in parse_trades_from_text() via a
# regex that looks for a newline followed by what looks like the start of a
# new trade entry. Real House PTR PDFs have three different patterns that
# all need to keep working together:
#   1. A real owner code (SP/DC/JT) followed by an UPPERCASE asset name —
#      the common case (e.g. "SP Apple Inc. Common Stock").
#   2. A real owner code followed by a LOWERCASE-starting asset name — some
#      genuine tickers/brands are lowercase-first (e.g. "SP iShares Bitcoin
#      Trust ETF", "SP e.l.f. Beauty, Inc.", "SP xAI"). Confirmed live
#      2026-08-28 (house_20034346, house_20035130, house_20033736): before
#      this fix, these trades were silently swallowed into the end of the
#      PRECEDING trade's block instead of being split out — the swallowed
#      trade's own data (date, amount, sometimes ticker) was lost, and its
#      ticker could even leak into the preceding trade's ticker field.
#   3. No owner code at all (self-owned trades) — these can't be reliably
#      split at their start at all (see the "* For the complete list"
#      header/footer + block-splitting caveats already tracked elsewhere),
#      but on real multi-page filings, the repeated column-header
#      boilerplate ("ID Owner Asset Transaction Date...") that PDF text
#      extraction leaves between pages incidentally provides a split point
#      ("ID" + space + "Owner" matches the same loose pattern used for
#      owner codes). Confirmed live 2026-08-28: naively restricting the
#      split pattern to only the three real owner codes broke this and
#      collapsed some real multi-page, all-self-owned filings from dozens
#      of trades down to a single merged block.

import unittest

from parser import parse_trades_from_text


def wrap_trade_section(body):
    """Wrap a raw trade-section body with the header/footer markers that
    parse_trades_from_text() uses to locate the transaction table."""
    return f"$200?\n{body}\n* For the complete list of asset type codes...\n"


class TestLowercaseAssetNameAfterOwnerCode(unittest.TestCase):
    def test_owner_coded_trade_with_lowercase_asset_name_is_split_out(self):
        text = wrap_trade_section(
            "SP Apollo Debt Solutions BDC Class S P 03/03/2026 04/09/2026 $1,001 - $15,000\n"
            "[OT]\n"
            "Filing Status: New\n"
            "SP iShares Bitcoin Trust ETF (IBIT) [ST] P 03/04/2026 04/09/2026 $100,001 -\n"
            "$250,000\n"
            "Filing Status: New\n"
        )
        trades = parse_trades_from_text(text)
        self.assertEqual(len(trades), 2)

        apollo, ishares = trades
        self.assertEqual(apollo["asset"], "Apollo Debt Solutions BDC Class S")
        self.assertEqual(apollo["ticker"], "")
        self.assertEqual(apollo["amount"], "$1,001 - $15,000")

        self.assertIn("iShares Bitcoin Trust ETF", ishares["asset"])
        self.assertEqual(ishares["ticker"], "IBIT")
        self.assertEqual(ishares["amount"], "$100,001 - $250,000")
        self.assertEqual(ishares["transaction_date"], "03/04/2026")

    def test_dotted_lowercase_brand_name_is_split_out(self):
        text = wrap_trade_section(
            "SP Chevron Corporation Common Stock S 12/16/2025 08/13/2026 $1,001 - $15,000\n"
            "(CVX) [ST]\n"
            "Filing Status: New\n"
            "SP e.l.f. Beauty, Inc. Common Stock S 12/16/2025 08/13/2026 $1,001 - $15,000\n"
            "(ELF) [ST]\n"
            "Filing Status: New\n"
        )
        trades = parse_trades_from_text(text)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["ticker"], "CVX")
        self.assertIn("e.l.f. Beauty", trades[1]["asset"])
        self.assertEqual(trades[1]["ticker"], "ELF")


class TestNoFalseSplitMidAssetName(unittest.TestCase):
    def test_short_uppercase_prefix_followed_by_lowercase_within_asset_name_not_split(self):
        # "BP p.l.c." starts with a real owner code look-alike ("BP") that
        # is NOT one of SP/DC/JT, immediately followed by lowercase text —
        # this must NOT be treated as a new trade boundary.
        text = wrap_trade_section(
            "SP Amazon.com, Inc. Common Stock P 03/19/2026 04/07/2026 $1,001 - $15,000\n"
            "(AMZN) [ST]\n"
            "Filing Status: New\n"
            "JT BP p.l.c. Common Stock (BP) [ST] P 03/19/2026 04/07/2026 $15,001 -\n"
            "$50,000\n"
            "Filing Status: New\n"
        )
        trades = parse_trades_from_text(text)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["ticker"], "AMZN")
        self.assertIn("BP p.l.c.", trades[1]["asset"])
        self.assertEqual(trades[1]["ticker"], "BP")
        self.assertEqual(trades[1]["amount"], "$15,001 - $50,000")


class TestSelfOwnedMultiPageSplittingUnaffected(unittest.TestCase):
    def test_repeated_page_header_still_splits_self_owned_trades(self):
        # No owner code at all (self-owned) — these rely on the repeated
        # "ID Owner Asset..." page-header boilerplate to split apart.
        text = wrap_trade_section(
            "3M Company Common Stock (MMM) P 01/17/2025 08/11/2025 $1,001 - $15,000\n"
            "[ST]\n"
            "Filing Status: New\n"
            "ID Owner Asset Transaction Date Notification Amount Cap.\n"
            "Type Date Gains >\n"
            "$200?\n"
            "Abbott Laboratories Common Stock P 10/23/2024 08/11/2025 $1,001 - $15,000\n"
            "(ABT) [ST]\n"
            "Filing Status: New\n"
        )
        trades = parse_trades_from_text(text)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["ticker"], "MMM")
        self.assertEqual(trades[1]["ticker"], "ABT")


if __name__ == "__main__":
    unittest.main()
