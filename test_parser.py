# test_parser.py — regression tests for parser.py's multi-line Description
# extraction (parse_single_trade()'s "D...:" field silently truncating to
# just its first line when a real PTR's Description wraps across multiple
# PDF text lines).
#
# Fixtures below mirror the exact text shape pdfplumber produces for real
# House PTR PDFs: field labels (Description/Comment/Subholding Of/Location)
# render as a single capital letter, null-byte (\x00) padding, then a colon
# — captured verbatim from real filings, e.g. "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00:"
# for Description and "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00:" for "Subholding Of:".

import parser


def test_single_line_description_still_extracted():
    block = (
        "SP Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 $15,001 -\n"
        "Stock (FERG) [ST] $50,000\n"
        "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
        "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: Automatic dividend reinvestment.\n"
    )
    assert parser.extract_description(block) == "Automatic dividend reinvestment."


def test_multiline_description_is_joined_not_truncated():
    # Captured (verbatim) from a real, currently-open House PTR filing: a
    # Putnam Investments-managed account liquidating a basket of securities
    # in one logical "full transaction", explained across 4 wrapped lines.
    block = (
        "Amazon.com, Inc. - Common Stock S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000\n"
        "(AMZN) [ST]\n"
        "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
        "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Putnam Investments\n"
        "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: The full transaction included the following sales: T \u2013 37.426 shares sold @ $27.645/share BRK/B \u2013 3 shares\n"
        "sold @ $493.42/share SPY \u2013 8.318 shares sold @ $670.024/share DIA \u2013 8.426 shares sold @ $470.985/share SPYD \u2013\n"
        "57.383 shares sold @ $46.04/share AMZN \u2013 25 shares sold @ $209.40/share AAPL \u2013 20.313 shares sold @ $253.45/share\n"
        "QQQ \u2013 4.105 shares sold @ $601.68/share PYPL \u2013 9.021 shares sold @ $47.735/share\n"
        "Apple Inc. - Common Stock (AAPL) S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000\n"
    )
    desc = parser.extract_description(block)
    assert desc.startswith("The full transaction included the following sales:")
    # All 4 wrapped lines' content must be present, not just the first.
    assert "PYPL" in desc
    assert "9.021 shares sold @ $47.735/share" in desc
    # Must NOT bleed into the next trade's own line.
    assert "Apple Inc." not in desc


def test_multiline_description_stops_at_field_label_line():
    block = (
        "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: Dividend reinvestment within a professionally\n"
        "managed account.\n"
        "L\x00\x00\x00\x00\x00\x00\x00: VA, US\n"
    )
    desc = parser.extract_description(block)
    assert desc == "Dividend reinvestment within a professionally managed account."
    assert "VA, US" not in desc


def test_multiline_description_stops_at_owner_coded_next_trade():
    block = (
        "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: The land we owned in an investment fund that\n"
        "purchased land for oil leases was sold.\n"
        "SP Microsoft Corp Common Stock S 01/05/2026 01/20/2026 $1,001 - $15,000\n"
    )
    desc = parser.extract_description(block)
    assert desc == "The land we owned in an investment fund that purchased land for oil leases was sold."
    assert "Microsoft" not in desc


def test_multiline_description_stops_at_unprefixed_next_trade():
    # A self-owned (no SP/DC/JT) trade is the only kind that starts a new
    # block without an owner code — detected via the transaction-type-letter
    # + date pattern instead.
    block = (
        "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: Professionally managed account. Structured product\n"
        "based on SPX.\n"
        "Apple Inc. - Common Stock (AAPL) S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000\n"
    )
    desc = parser.extract_description(block)
    assert desc == "Professionally managed account. Structured product based on SPX."
    assert "Apple" not in desc


def test_multiline_description_stops_at_page_header_boilerplate():
    block = (
        "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: Bond reached maturity\n"
        "ID Owner Asset Transaction Date Notification Amount Cap.\n"
    )
    desc = parser.extract_description(block)
    assert desc == "Bond reached maturity"


def test_multiline_description_stops_at_footnote():
    block = (
        "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: Value after sale is <$1,000.\n"
        "* For the complete list of asset type abbreviations, see page 8.\n"
    )
    desc = parser.extract_description(block)
    assert desc == "Value after sale is <$1,000."


def test_no_description_label_returns_empty_string():
    block = "SP Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 $15,001 - $50,000\n"
    assert parser.extract_description(block) == ""


def test_parse_single_trade_end_to_end_recovers_full_description():
    # Same real multi-line block as above, but through the full
    # parse_single_trade() entry point (not just extract_description()
    # directly), proving the fix is actually wired in.
    block = (
        "Amazon.com, Inc. - Common Stock S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000\n"
        "(AMZN) [ST]\n"
        "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
        "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Putnam Investments\n"
        "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: The full transaction included the following sales: T \u2013 37.426 shares sold @ $27.645/share BRK/B \u2013 3 shares\n"
        "sold @ $493.42/share SPY \u2013 8.318 shares sold @ $670.024/share DIA \u2013 8.426 shares sold @ $470.985/share SPYD \u2013\n"
        "57.383 shares sold @ $46.04/share AMZN \u2013 25 shares sold @ $209.40/share AAPL \u2013 20.313 shares sold @ $253.45/share\n"
        "QQQ \u2013 4.105 shares sold @ $601.68/share PYPL \u2013 9.021 shares sold @ $47.735/share\n"
        "Apple Inc. - Common Stock (AAPL) S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000\n"
    )
    trade = parser.parse_single_trade(block)
    assert trade is not None
    assert "PYPL" in trade["description"]
    assert "9.021 shares sold @ $47.735/share" in trade["description"]
