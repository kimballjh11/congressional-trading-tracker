# test_parser.py — Tests for House PTR trade-block asset-name extraction
#
# Real House PTR PDFs render field labels (Filing Status:, Subholding Of:,
# Location:, Description:) with a mangled font that pdfplumber extracts as a
# leading letter followed by NUL (\x00) padding, e.g. "F\x00\x00\x00\x00\x00
# S\x00\x00\x00\x00\x00: New" for "Filing Status: New". The fixtures below
# use that exact real-world encoding rather than the readable label text.
#
# All fixtures are built from real filings downloaded live from
# disclosures-clerk.house.gov (filing IDs noted per fixture) to make sure the
# wrapping patterns being tested actually occur in production, not just in
# hand-constructed edge cases.

import unittest

from parser import parse_single_trade, parse_trades_from_text


# From filing 20033751 (Rep. Richard W. Allen). The asset name's "Stock"
# suffix and the ticker parenthetical wrap to the line after the transaction
# type/dates/amount.
STOCK_NAME_WRAPS_AFTER_DATE = (
    "SP Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 $15,001 -\n"
    "Stock (FERG) [ST] $50,000\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: R.W. Allen & Associates, Inc. > RWA&A - Securities"
)

# From filing 20033751. The asset name, ticker, and cap-gains bracket all sit
# on the same line as the transaction type letter — no wrapping. Guards
# against regressing the common (non-wrapped) case.
STOCK_NAME_NO_WRAP = (
    "SP Netflix, Inc. - Common Stock (NFLX) S 12/12/2025 01/06/2026 $1,001 - $15,000\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New"
)

# From filing 20034892 (US Treasury note). The maturity-date/coupon-rate
# portion of the asset name wraps to the line after the amount's lower
# bound, and the amount's upper bound comes after that continuation text —
# interleaving asset text between the two halves of the dollar-amount range.
BOND_NAME_WRAPS_AROUND_AMOUNT = (
    "SP US Treasury Note 3.75% DUE S 04/16/2026 05/04/2026 $100,001 -\n"
    "12/31/28 (91282CJR3) [GS] $250,000\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: R.W. Allen & Associates, Inc. > RWA&A - Securities"
)

# From filing 20034368 (Rep. Steve Cohen), a self-owned municipal bond. The
# asset name continues across two more lines after the amount, before the
# cap-gains bracket.
MUNI_BOND_NAME_WRAPS_MULTIPLE_LINES = (
    "METROPOLITAN GOVT NA S 03/16/2026 04/14/2026 $1,001 - $15,000\n"
    "DAVIDSON CNTY TENN HEALTH &\n"
    "ED L FACS BRD 3.750% 03/15/28 B\n"
    "[GS]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Stephens Advantage Account"
)


class TestAssetNameWrapping(unittest.TestCase):
    def test_stock_name_recovers_text_wrapped_after_date(self):
        trade = parse_single_trade(STOCK_NAME_WRAPS_AFTER_DATE)
        self.assertEqual(trade["asset"], "Ferguson Enterprises Inc. Common Stock (FERG)")
        self.assertEqual(trade["ticker"], "FERG")
        self.assertEqual(trade["transaction_type"], "Purchase")
        self.assertEqual(trade["transaction_date"], "12/12/2025")
        self.assertEqual(trade["notification_date"], "01/06/2026")
        self.assertEqual(trade["amount"], "$15,001 - $50,000")

    def test_stock_name_unchanged_when_not_wrapped(self):
        trade = parse_single_trade(STOCK_NAME_NO_WRAP)
        self.assertEqual(trade["asset"], "Netflix, Inc. - Common Stock (NFLX)")
        self.assertEqual(trade["ticker"], "NFLX")
        self.assertEqual(trade["transaction_type"], "Sale")
        self.assertEqual(trade["amount"], "$1,001 - $15,000")

    def test_bond_name_recovers_maturity_date_interleaved_with_amount(self):
        trade = parse_single_trade(BOND_NAME_WRAPS_AROUND_AMOUNT)
        self.assertEqual(trade["asset"], "US Treasury Note 3.75% DUE 12/31/28 (91282CJR3)")
        self.assertEqual(trade["transaction_type"], "Sale")
        self.assertEqual(trade["transaction_date"], "04/16/2026")
        self.assertEqual(trade["notification_date"], "05/04/2026")
        self.assertEqual(trade["amount"], "$100,001 - $250,000")

    def test_muni_bond_name_recovers_all_wrapped_lines(self):
        trade = parse_single_trade(MUNI_BOND_NAME_WRAPS_MULTIPLE_LINES)
        self.assertEqual(
            trade["asset"],
            "METROPOLITAN GOVT NA DAVIDSON CNTY TENN HEALTH & ED L FACS BRD 3.750% 03/15/28 B",
        )
        self.assertEqual(trade["amount"], "$1,001 - $15,000")

    def test_embedded_asset_date_not_mistaken_for_transaction_date(self):
        # The bond's own maturity date ("12/31/28") must survive even though
        # it looks like a transaction date — only the two real dates
        # (transaction_date, notification_date) should be stripped from the
        # recovered asset text.
        trade = parse_single_trade(BOND_NAME_WRAPS_AROUND_AMOUNT)
        self.assertIn("12/31/28", trade["asset"])

    def test_full_multi_trade_section_end_to_end(self):
        # Sanity-check the fix through the higher-level entry point too,
        # with more than one trade block in the section.
        text = (
            "ID Owner Asset Transaction Date Notification Amount Cap.\n"
            "Type Date Gains >\n"
            "$200?\n"
            + STOCK_NAME_WRAPS_AFTER_DATE
            + "\n"
            + STOCK_NAME_NO_WRAP
            + "\n"
            "* For the complete list of asset type abbreviations, please visit "
            "https://fd.house.gov/reference/asset-type-codes.aspx."
        )
        trades = parse_trades_from_text(text)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["asset"], "Ferguson Enterprises Inc. Common Stock (FERG)")
        self.assertEqual(trades[1]["asset"], "Netflix, Inc. - Common Stock (NFLX)")


if __name__ == "__main__":
    unittest.main()
