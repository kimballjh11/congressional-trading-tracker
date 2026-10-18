# test_parser.py — Regression tests for parser.py's multi-line Description
# extraction fix.
#
# Background: House PTR PDFs render field labels with embedded null bytes
# (e.g. "D\x00\x00...: <text>") due to the font encoding, and Description
# text frequently wraps across multiple lines for longer explanations
# (spinoffs, itemized partial-sale breakdowns, bond terms, etc.). The old
# regex (`r"D\x00*\w*\s*:\s*(.+?)(?:\n|$)"`) stopped at the first newline,
# silently truncating any wrapped continuation. extract_description() fixes
# this by walking forward line-by-line and only stopping when a line looks
# like a new field label, a new trade, the repeated page header, or the
# trailing footnote.
#
# Run with: python3 test_parser.py

from parser import extract_description, parse_single_trade

NULL5 = "\x00" * 5
NULL10 = "\x00" * 10


def test_single_line_description_still_works():
    block = (
        f"Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 $15,001 -\n"
        f"Stock (FERG) [ST] $50,000\n"
        f"F{NULL5} S{NULL5}: New\n"
        f"D{NULL10}: A short one-line description."
    )
    assert extract_description(block) == "A short one-line description."


def test_multiline_description_is_fully_captured():
    # Real-world example (House filing 20034960, Rep. Dingell): the
    # Description explaining a spinoff wraps onto a second line.
    block = (
        f"Honeywell Aerospace Inc. - Common E 06/29/2026 07/06/2026 $50,001 -\n"
        f"Stock (HONAV) [ST] $100,000\n"
        f"F{NULL5} S{NULL5}: New\n"
        f"S{NULL10} O\x00: Morgan Stanley Smith Barney LLC Brokerage Account\n"
        f"D{NULL10}: Asset acquired when certain Honeywell International Inc. (HON) shares were exchanged for Honeywell\n"
        f"Aerospace Inc. (HONAV) shares due to a spinoff."
    )
    assert extract_description(block) == (
        "Asset acquired when certain Honeywell International Inc. (HON) "
        "shares were exchanged for Honeywell Aerospace Inc. (HONAV) shares "
        "due to a spinoff."
    )


def test_multiline_description_stops_before_next_owner_coded_trade():
    # A Description that wraps right up against the next (owner-coded)
    # trade in the same block must not swallow that trade's text.
    block = (
        f"D{NULL10}: 75,000 units\n"
        f"JT Ohio St Gen Oblig 5.00% 11/01/34 P 01/07/2026 01/31/2026 $15,001 -"
    )
    assert extract_description(block) == "75,000 units"


def test_multiline_description_stops_before_unprefixed_next_trade():
    # Real-world example (House filing 20034201): a self-owned (no owner
    # code) trade immediately follows the Description with no blank line
    # or label in between — detected via the transaction-type+date pattern.
    block = (
        f"D{NULL10}: The full transaction included the following sales: T\n"
        f"sold @ $27.645/share BRK/B – 3 shares sold @ $493.42/share\n"
        f"Apple Inc. - Common Stock (AAPL) S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000"
    )
    desc = extract_description(block)
    assert desc == (
        "The full transaction included the following sales: T sold @ "
        "$27.645/share BRK/B – 3 shares sold @ $493.42/share"
    )
    assert "Apple" not in desc


def test_multiline_description_stops_before_repeated_page_header():
    block = (
        f"D{NULL10}: Ticker 2802 JP\n"
        f"ID Owner Asset Transaction Date Notification Amount Cap."
    )
    assert extract_description(block) == "Ticker 2802 JP"


def test_multiline_description_stops_before_footnote():
    block = (
        f"D{NULL10}: See attached explanation for full detail.\n"
        f"* For the complete list of asset type abbreviations, please visit https://fd.house.gov/reference/asset-type-codes.aspx."
    )
    assert extract_description(block) == "See attached explanation for full detail."


def test_multiline_description_stops_before_next_field_label():
    block = (
        f"D{NULL10}: dividend reinvestment\n"
        f"C{NULL5}: Yes"
    )
    assert extract_description(block) == "dividend reinvestment"


def test_no_description_returns_empty_string():
    block = "Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 $15,001 - $50,000"
    assert extract_description(block) == ""


def test_parse_single_trade_uses_multiline_description():
    block = (
        f"SP Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 $15,001 -\n"
        f"Stock (FERG) [ST] $50,000\n"
        f"F{NULL5} S{NULL5}: New\n"
        f"D{NULL10}: Purchased as part of a diversified retirement account\n"
        f"managed by an independent financial advisor with no input from the filer."
    )
    trade = parse_single_trade(block)
    assert trade["description"] == (
        "Purchased as part of a diversified retirement account managed by "
        "an independent financial advisor with no input from the filer."
    )
    assert trade["owner"] == "SP"
    assert trade["ticker"] == "FERG"
    assert trade["transaction_type"] == "Purchase"


TESTS = [
    test_single_line_description_still_works,
    test_multiline_description_is_fully_captured,
    test_multiline_description_stops_before_next_owner_coded_trade,
    test_multiline_description_stops_before_unprefixed_next_trade,
    test_multiline_description_stops_before_repeated_page_header,
    test_multiline_description_stops_before_footnote,
    test_multiline_description_stops_before_next_field_label,
    test_no_description_returns_empty_string,
    test_parse_single_trade_uses_multiline_description,
]


if __name__ == "__main__":
    failures = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {test.__name__}: {e}")

    print(f"\n{len(TESTS) - failures}/{len(TESTS)} tests passed.")
    if failures:
        raise SystemExit(1)
