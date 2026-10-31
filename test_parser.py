# test_parser.py — Regression tests for parser.py's House PTR trade-block
# splitting and asset-name extraction.
#
# Fixtures below are real text captured verbatim (via extract_text_from_pdf)
# from currently-open, real House PTR filings. Each one reproduces a distinct
# way the old owner-code-based block split and date-anchored asset extraction
# silently corrupted or dropped real trade data:
#
#   - house_20034368: a municipal bond whose name wraps across 3 lines; the
#     continuation "ED L FACS BRD..." (from "...Health & Ed'l Facs Brd...")
#     looks exactly like an "ED" owner code followed by a capitalized word,
#     so the old split chopped the bond's own trade in two, truncating its
#     name and spawning a bogus all-empty "ED"-owner phantom trade.
#   - house_20034895: two back-to-back preferred-stock trades whose shared
#     "Series D Cumulative..." wrap line ("D Cumulative...") looks like a
#     "D" owner code, corrupting both trades' asset names and merging parts
#     of adjacent trades together.
#   - house_20034315: "US Treasury Note..." — the old owner regex matched
#     "US" as a bogus owner code and "Stock (FERG)"-style text immediately
#     after a date was dropped entirely by the old date-anchored split.
#   - repeated page header: a multi-page filing repeats the table's column
#     header ("ID Owner Asset Transaction Date...") inline, which the old
#     split mistook for an "ID"-owner trade and merged with real data,
#     producing a garbled phantom trade with nonsense ticker/amount values.

import pytest

from parser import parse_trades_from_text, parse_single_trade, split_trade_blocks


MUNI_BOND_WRAP = (
    "$200?\n"
    "METROPOLITAN GOVT NA S 03/16/2026 04/14/2026 $1,001 - $15,000\n"
    "DAVIDSON CNTY TENN HEALTH &\n"
    "ED L FACS BRD 3.750% 03/15/28 B\n"
    "[GS]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Stephens Advantage Account\n"
    "* For the complete list"
)

ADJACENT_PREFERRED_STOCK_WRAP = (
    "$200?\n"
    "Alliance Resource Partners, L.P. - S (partial) 06/18/2026 07/01/2026 $15,001 -\n"
    "Common Units Representing Limited $50,000\n"
    "Partnership Interests (ARLP) [ST]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "Ellington Financial Inc. 7.00% Series S (partial) 06/18/2026 07/01/2026 $15,001 -\n"
    "D Cumulative Perpetual Redeemable $50,000\n"
    "Preferred Stock (EFC$D) [ST]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "* For the complete list"
)

US_TREASURY_OWNER_FALSE_POSITIVE = (
    "$200?\n"
    "US Treasury Note 3.5% DUE 1/31/30 P 03/24/2026 04/08/2026 $15,001 -\n"
    "(91282CGJ4) [GS] $50,000\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: SCH1\n"
    "* For the complete list"
)

REPEATED_PAGE_HEADER = (
    "$200?\n"
    "Amazon.com, Inc. - Common Stock S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000\n"
    "(AMZN) [ST]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "ID Owner Asset Transaction Date Notification Amount Cap.\n"
    "Type Date Gains >\n"
    "$200?\n"
    "Apple Inc. - Common Stock S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000\n"
    "(AAPL) [ST]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "* For the complete list"
)

DOCSTRING_EXAMPLE = (
    "$200?\n"
    "SP Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 $15,001 -\n"
    "Stock (FERG) [ST] $50,000\n"
    "Filing Status: New\n"
    "* For the complete list"
)


def test_muni_bond_name_not_truncated_or_split_into_phantom_trade():
    trades = parse_trades_from_text(MUNI_BOND_WRAP)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["owner"] == ""
    assert "DAVIDSON CNTY TENN HEALTH" in trade["asset"]
    assert "ED L FACS BRD" in trade["asset"]
    assert trade["transaction_type"] == "Sale"
    assert trade["amount"] == "$1,001 - $15,000"


def test_adjacent_trades_not_merged_by_shared_series_wrap():
    trades = parse_trades_from_text(ADJACENT_PREFERRED_STOCK_WRAP)
    assert len(trades) == 2

    first, second = trades
    assert "Alliance Resource Partners" in first["asset"]
    assert first["ticker"] == "ARLP"
    assert first["amount"] == "$15,001 - $50,000"
    # The first trade's asset must not have leaked the second trade's name.
    assert "Ellington" not in first["asset"]

    assert "Ellington Financial" in second["asset"]
    assert "Series D Cumulative Perpetual Redeemable Preferred Stock" in second["asset"]
    assert second["amount"] == "$15,001 - $50,000"


def test_us_treasury_not_misread_as_owner_code():
    trades = parse_trades_from_text(US_TREASURY_OWNER_FALSE_POSITIVE)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["owner"] == ""
    assert trade["asset"].startswith("US Treasury Note")
    assert "3.5% DUE 1/31/30" in trade["asset"]
    assert trade["transaction_type"] == "Purchase"
    assert trade["amount"] == "$15,001 - $50,000"


def test_repeated_page_header_does_not_corrupt_or_spawn_phantom_trade():
    trades = parse_trades_from_text(REPEATED_PAGE_HEADER)
    assert len(trades) == 2
    tickers = {t["ticker"] for t in trades}
    assert tickers == {"AMZN", "AAPL"}
    for t in trades:
        assert t["owner"] != "ID"
        assert t["amount"] == "$1,001 - $15,000"


def test_docstring_example_still_parses_correctly():
    trades = parse_trades_from_text(DOCSTRING_EXAMPLE)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["owner"] == "SP"
    assert trade["asset"] == "Ferguson Enterprises Inc. Common Stock (FERG)"
    assert trade["ticker"] == "FERG"
    assert trade["transaction_type"] == "Purchase"
    assert trade["amount"] == "$15,001 - $50,000"


def test_parse_single_trade_drops_all_empty_blocks():
    # A stray metadata-only fragment (e.g. a continuation line that slipped
    # past the block split) must not surface as a phantom trade.
    assert parse_single_trade("F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New") is None


def test_split_trade_blocks_splits_on_filing_status_footer():
    section = (
        "SP Foo Inc. Common P 01/01/2026 01/15/2026 $1,001 - $15,000\n"
        "Stock (FOO) [ST]\n"
        "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
        "DC Bar Corp. Common S 02/01/2026 02/15/2026 $1,001 - $15,000\n"
        "Stock (BAR) [ST]\n"
        "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New"
    )
    blocks = split_trade_blocks(section)
    assert len(blocks) == 2
    assert blocks[0].startswith("SP Foo Inc.")
    assert blocks[1].startswith("DC Bar Corp.")
