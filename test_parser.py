# test_parser.py — Regression tests for parser.py using real filing text captured
# from disclosures-clerk.house.gov (no network access required to run).
#
# Run directly:  python3 test_parser.py
# Or with pytest: pytest test_parser.py

from parser import parse_trades_from_text

# Real extracted text from House PTR filing #20034190 (Rep. Thomas H. Kean Jr,
# filed 2026-03-18). This filing spans two PDF pages, so pdfplumber's combined
# text repeats the table's column-header row ("ID Owner Asset Transaction
# Date Notification Amount Cap. / Type Date Gains > / $200?") once per page,
# and the "Waters Corporation" trade's ticker wraps onto the second page,
# landing right after that repeated header.
MULTI_PAGE_FILING_TEXT = (
    "Filing ID #20034190\n"
    "P\x00\x00\x00\x00\x00\x00\x00 T\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00 R\x00\x00\x00\x00\x00\n"
    "Clerk of the House of Representatives \u2022 Legislative Resource Center \u2022 B81 Cannon Building \u2022 Washington, DC 20515\n"
    "F\x00\x00\x00\x00 I\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n"
    "Name: Hon. Thomas H. Kean Jr\n"
    "Status: Member\n"
    "State/District: NJ07\n"
    "T\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n"
    "ID Owner Asset Transaction Date Notification Amount Cap.\n"
    "Type Date Gains >\n"
    "$200?\n"
    "Alphabet Inc. - Class A Common S (partial) 02/05/2026 03/03/2026 $15,001 -\n"
    "Stock (GOOGL) [ST] $50,000\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Kean Family Partnership\n"
    "First Citizens BancShares, Inc. - Class P 02/05/2026 03/03/2026 $1,001 - $15,000\n"
    "A Common Stock (FCNCA) [ST]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Kean Family Partnership\n"
    "Linde plc - Ordinary Shares (LIN) P 02/18/2026 03/03/2026 $1,001 - $15,000\n"
    "[ST]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Kean Family Partnership\n"
    "U.S. Treasury Note [GS] P 02/18/2026 03/03/2026 $50,001 -\n"
    "$100,000\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Kean Family Partnership\n"
    "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: 0.750%, 4/30/2026\n"
    "U.S. Treasury Note [GS] P 02/18/2026 03/03/2026 $50,001 -\n"
    "$100,000\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Kean Family Partnership\n"
    "D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00: 4.625%, 10/15/2026\n"
    "Waters Corporation Common Stock S (partial) 02/13/2026 03/03/2026 $1,001 - $15,000\n"
    "(WAT) [ST]\n"
    "ID Owner Asset Transaction Date Notification Amount Cap.\n"
    "Type Date Gains >\n"
    "$200?\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "S\x00\x00\x00\x00\x00\x00\x00\x00\x00 O\x00: Kean Family Partnership\n"
    "* For the complete list of asset type abbreviations, please visit https://fd.house.gov/reference/asset-type-codes.aspx.\n"
    "I\x00\x00\x00\x00\x00\x00\x00\x00\x00 V\x00\x00\x00\x00\x00\x00 D\x00\x00\x00\x00\x00\x00\n"
    "Kean Family Partnership (33% Interest)\n"
    "L\x00\x00\x00\x00\x00\x00\x00: US\n"
    "I\x00\x00\x00\x00\x00\x00 P\x00\x00\x00\x00\x00 O\x00\x00\x00\x00\x00\x00\x00\x00\n"
    "Yes No\n"
    "C\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00 \x00\x00\x00 S\x00\x00\x00\x00\x00\x00\x00\x00\n"
    "I CERTIFY that the statements I have made on the attached Periodic Transaction Report are true, complete, and correct to the best of\n"
    "my knowledge and belief. Further, I CERTIFY that I have disclosed all transactions as required by the STOCK Act.\n"
    "Digitally Signed: Hon. Thomas H. Kean Jr, 03/18/2026\n"
)


def test_multi_page_filing_has_no_phantom_header_trades():
    trades = parse_trades_from_text(MULTI_PAGE_FILING_TEXT)
    phantom = [t for t in trades if t["owner"] == "ID"]
    assert not phantom, f"repeated page-header text was mis-parsed as trade(s): {phantom}"


def test_multi_page_filing_extracts_exactly_six_trades():
    trades = parse_trades_from_text(MULTI_PAGE_FILING_TEXT)
    assert len(trades) == 6, f"expected 6 real trades, got {len(trades)}: {trades}"


def test_trade_wrapping_across_page_break_keeps_its_ticker():
    trades = parse_trades_from_text(MULTI_PAGE_FILING_TEXT)
    waters = next((t for t in trades if "Waters" in t["asset"]), None)
    assert waters is not None, "Waters Corporation trade was not found at all"
    assert waters["ticker"] == "WAT", (
        f"ticker for a trade wrapping across the page-header boilerplate "
        f"was lost or corrupted: {waters}"
    )
    assert waters["transaction_type"] == "Sale (partial)"
    assert waters["amount"] == "$1,001 - $15,000"


def test_description_field_with_null_padded_label_still_parses():
    trades = parse_trades_from_text(MULTI_PAGE_FILING_TEXT)
    treasury_notes = [t for t in trades if "Treasury Note" in t["asset"]]
    assert len(treasury_notes) == 2
    descriptions = sorted(t["description"] for t in treasury_notes)
    assert descriptions == ["0.750%, 4/30/2026", "4.625%, 10/15/2026"]


SELF_OWNED_MULTI_TRADE_TEXT = (
    "Filing ID #20034138\n"
    "State/District: WA10\n"
    "ID Owner Asset Transaction Date Notification Amount Cap.\n"
    "Type Date Gains >\n"
    "$200?\n"
    "Alphabet Inc. - Class A Common P 02/26/2026 03/05/2026 $1,001 - $15,000\n"
    "Stock (GOOGL) [ST]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "Amazon.com, Inc. - Common Stock P 02/26/2026 03/05/2026 $1,001 - $15,000\n"
    "(AMZN) [ST]\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "AT&T Inc. (T) S 02/26/2026 03/05/2026 $1,001 - $15,000\n"
    "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
    "* For the complete list of asset type abbreviations, please visit https://fd.house.gov/reference/asset-type-codes.aspx.\n"
)


def test_self_owned_trades_with_no_owner_code_are_not_merged():
    # When a member holds an asset directly (no spouse/dependent/joint code),
    # the PDF's owner column is blank, so consecutive trades have nothing
    # visually distinguishing where one ends and the next begins other than
    # the mandatory "Filing Status:" footer.
    trades = parse_trades_from_text(SELF_OWNED_MULTI_TRADE_TEXT)
    assert len(trades) == 3, f"expected 3 separate trades, got {len(trades)}: {trades}"
    tickers = [t["ticker"] for t in trades]
    assert tickers == ["GOOGL", "AMZN", "T"], tickers
    assert all(t["owner"] == "" for t in trades)


def test_short_allcaps_asset_prefix_is_not_mistaken_for_owner_code():
    # "US Treasury Bills..." and "GE HealthCare..." start with a short
    # all-caps word followed by a space, which looks just like a genuine
    # SP/DC/JT owner-code prefix unless we restrict the match to the known
    # codes.
    text = (
        "ID Owner Asset Transaction Date Notification Amount Cap.\n"
        "Type Date Gains >\n"
        "$200?\n"
        "US Treasury Bills, due 8/20/2026 P 02/23/2026 03/11/2026 $50,001 -\n"
        "$100,000\n"
        "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
        "GE HealthCare Technologies Inc. - S 03/25/2026 03/26/2026 $1,001 - $15,000\n"
        "Common Stock (GEHC) [ST]\n"
        "F\x00\x00\x00\x00\x00 S\x00\x00\x00\x00\x00: New\n"
        "* For the complete list of asset type abbreviations, please visit https://fd.house.gov/reference/asset-type-codes.aspx.\n"
    )
    trades = parse_trades_from_text(text)
    assert len(trades) == 2, f"expected 2 trades, got {len(trades)}: {trades}"
    assert all(t["owner"] == "" for t in trades), trades
    assert trades[0]["asset"].startswith("US Treasury Bills"), trades[0]["asset"]
    assert trades[1]["asset"].startswith("GE HealthCare"), trades[1]["asset"]


def run_all():
    tests = [
        test_multi_page_filing_has_no_phantom_header_trades,
        test_multi_page_filing_extracts_exactly_six_trades,
        test_trade_wrapping_across_page_break_keeps_its_ticker,
        test_description_field_with_null_padded_label_still_parses,
        test_self_owned_trades_with_no_owner_code_are_not_merged,
        test_short_allcaps_asset_prefix_is_not_mistaken_for_owner_code,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    run_all()
