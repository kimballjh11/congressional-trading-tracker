# test_scraper.py — Regression tests for scraper.py using real HTML rows captured
# from disclosures-clerk.house.gov (no network access required to run).
#
# Run directly:  python3 test_scraper.py
# Or with pytest: pytest test_scraper.py

from scraper import parse_filings_html

# Real row from the House Clerk search results for a filing with an 8-digit
# PDF filename (the common case).
ROW_8_DIGIT = """
<tr role="row">
<td>Allen, Richard W.</td>
<td>GA12</td>
<td>2026</td>
<td>PTR Original</td>
<td><a href="public_disc/ptr-pdfs/2026/20033751.pdf">PDF</a></td>
</tr>
"""

# Real row from the House Clerk search results for a filing with a 7-digit
# PDF filename. These are real, current filings (not a legacy/rare edge
# case) — confirmed live on 2026-07-18, ~11% of all 2026 PTR filings use
# this shorter numbering.
ROW_7_DIGIT = """
<tr role="row">
<td>Harshbarger, Diana</td>
<td>TN01</td>
<td>2026</td>
<td>PTR Original</td>
<td><a href="public_disc/ptr-pdfs/2026/9115812.pdf">PDF</a></td>
</tr>
"""


def test_8_digit_filing_id():
    filings = parse_filings_html(ROW_8_DIGIT)
    assert len(filings) == 1
    assert filings[0]["filing_id"] == "house_20033751"


def test_7_digit_filing_id_not_mangled():
    """
    Before the fix, the filing_id regex hardcoded exactly 8 digits, so a
    7-digit filename like 9115812.pdf fell through to using the *entire*
    pdf_path as the ID: "house_public_disc/ptr-pdfs/2026/9115812.pdf".
    """
    filings = parse_filings_html(ROW_7_DIGIT)
    assert len(filings) == 1
    assert filings[0]["filing_id"] == "house_9115812"
    assert "public_disc" not in filings[0]["filing_id"]
    assert "/" not in filings[0]["filing_id"]


def test_non_ptr_rows_are_skipped():
    non_ptr_row = ROW_8_DIGIT.replace("PTR Original", "Annual Disclosure")
    filings = parse_filings_html(non_ptr_row)
    assert filings == []


def run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  PASS: {t.__name__}")
    print(f"\n{len(tests)} tests passed.")


if __name__ == "__main__":
    run_all()
