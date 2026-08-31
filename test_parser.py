# test_parser.py — Tests for Senate PTR HTML parsing (parse_senate_html / extract_cell_text)
#
# The Exchange-transaction fixture below mirrors the exact table structure of a
# real, live Senate eFD PTR report (Sen. Wyden, filed 2026-08-08, report id
# 5ecc9b5c-07c1-4ec1-bd4a-2db759eff299) — confirmed via a direct GET against
# https://efdsearch.senate.gov/search/view/ptr/5ecc9b5c-07c1-4ec1-bd4a-2db759eff299/
# and cross-checked against an independent third-party scraper's parse of the
# same report (ticker "AMCR", asset name "BERY - Berry Global Group, Inc.
# (Exchanged) Amcor plc Ordinary Shares (Received)").

import unittest

from parser import parse_senate_html, extract_cell_text
from bs4 import BeautifulSoup


EXCHANGE_TABLE_HTML = """
<table class="table table-striped">
    <thead>
        <tr class="header">
            <th scope="col">#</th>
            <th scope="col">Transaction Date</th>
            <th scope="col">Owner</th>
            <th scope="col">Ticker</th>
            <th scope="col">Asset Name</th>
            <th scope="col">Asset Type</th>
            <th scope="col">Type</th>
            <th scope="col">Amount</th>
            <th scope="col">Comment</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>1</td>
            <td>
                04/30/2025
            </td>
            <td>Spouse</td>
            <td>
                --
                <br/>
                <a href="https://finance.yahoo.com/quote/AMCR" target="_blank">AMCR</a>
            </td>
            <td>
                BERY - Berry Global Group, Inc. (Exchanged)
                <br/>
                Amcor plc Ordinary Shares (Received)
            </td>
            <td>Stock</td>
            <td>Exchange</td>
            <td>$100,001 - $250,000</td>
            <td>--</td>
        </tr>
    </tbody>
</table>
"""

SIMPLE_PURCHASE_TABLE_HTML = """
<table class="table table-striped">
    <thead>
        <tr class="header">
            <th scope="col">#</th>
            <th scope="col">Transaction Date</th>
            <th scope="col">Owner</th>
            <th scope="col">Ticker</th>
            <th scope="col">Asset Name</th>
            <th scope="col">Asset Type</th>
            <th scope="col">Type</th>
            <th scope="col">Amount</th>
            <th scope="col">Comment</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>1</td>
            <td>03/19/2026</td>
            <td>Self</td>
            <td><a href="https://finance.yahoo.com/quote/NVDA" target="_blank">NVDA</a></td>
            <td>NVIDIA Corporation - Common Stock</td>
            <td>Stock</td>
            <td>Purchase</td>
            <td>$1,001 - $15,000</td>
            <td>--</td>
        </tr>
    </tbody>
</table>
"""


class TestExtractCellText(unittest.TestCase):
    def test_drops_placeholder_and_joins_with_space(self):
        soup = BeautifulSoup(EXCHANGE_TABLE_HTML, "html.parser")
        ticker_cell = soup.find_all("td")[3]
        asset_cell = soup.find_all("td")[4]
        self.assertEqual(extract_cell_text(ticker_cell), "AMCR")
        self.assertEqual(
            extract_cell_text(asset_cell),
            "BERY - Berry Global Group, Inc. (Exchanged) Amcor plc Ordinary Shares (Received)",
        )

    def test_lone_placeholder_becomes_empty_string(self):
        soup = BeautifulSoup(EXCHANGE_TABLE_HTML, "html.parser")
        comment_cell = soup.find_all("td")[8]
        self.assertEqual(extract_cell_text(comment_cell), "")

    def test_plain_single_line_cell_unaffected(self):
        soup = BeautifulSoup(SIMPLE_PURCHASE_TABLE_HTML, "html.parser")
        owner_cell = soup.find_all("td")[2]
        asset_cell = soup.find_all("td")[4]
        self.assertEqual(extract_cell_text(owner_cell), "Self")
        self.assertEqual(extract_cell_text(asset_cell), "NVIDIA Corporation - Common Stock")


class TestParseSenateHtmlExchange(unittest.TestCase):
    def setUp(self):
        self.filing = {"representative": "Wyden, Ron", "date_submitted": "08/08/2026"}

    def test_exchange_transaction_ticker_and_asset_are_clean(self):
        trades = parse_senate_html(EXCHANGE_TABLE_HTML, self.filing)
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade["ticker"], "AMCR")
        self.assertEqual(
            trade["asset"],
            "BERY - Berry Global Group, Inc. (Exchanged) Amcor plc Ordinary Shares (Received)",
        )
        self.assertEqual(trade["owner"], "Spouse")
        self.assertEqual(trade["transaction_type"], "Exchange")
        self.assertEqual(trade["transaction_date"], "04/30/2025")
        self.assertEqual(trade["amount"], "$100,001 - $250,000")
        self.assertEqual(trade["description"], "")

    def test_simple_purchase_still_parses_correctly(self):
        trades = parse_senate_html(SIMPLE_PURCHASE_TABLE_HTML, self.filing)
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade["ticker"], "NVDA")
        self.assertEqual(trade["asset"], "NVIDIA Corporation - Common Stock")
        self.assertEqual(trade["owner"], "Self")
        self.assertEqual(trade["transaction_type"], "Purchase")
        self.assertEqual(trade["transaction_date"], "03/19/2026")


if __name__ == "__main__":
    unittest.main()
