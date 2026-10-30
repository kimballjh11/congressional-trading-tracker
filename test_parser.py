# test_parser.py — Tests for parser.py
# Fixtures captured verbatim (pdfplumber text extraction output) from real,
# live House PTR filings, to reproduce real-world parsing bugs.

from parser import extract_filer_info


# From house_20033732 (Fields, Cleo / LA06) — a real, currently-sitting member
# (seated via a 2026 special election) whose PTR header renders the filer's
# name WITHOUT the "Hon." title prefix that every other sampled filing has.
FIELDS_NO_HON_TITLE = (
    "Filing ID #20033732\n"
    "Clerk of the House of Representatives\n"
    "Name: Cleo Fields\n"
    "Status: Member\n"
    "State/District: LA06\n"
    "ID Owner Asset Transaction Date Notification Amount Cap.\n"
    "Type Date Gains >\n"
    "$200?\n"
    "Alphabet Inc. - Class A Common P 12/26/2025 12/26/2025 $50,001 -\n"
)

# From house_20034201 (Alford, Mark / MO04) — an ordinary filing with the
# standard "Hon." title prefix, used as a regression check.
ALFORD_WITH_HON_TITLE = (
    "Filing ID #20034201\n"
    "Clerk of the House of Representatives\n"
    "Name: Hon. Mark Alford\n"
    "Status: Member\n"
    "State/District: MO04\n"
    "ID Owner Asset Transaction Date Notification Amount Cap.\n"
    "Type Date Gains >\n"
    "$200?\n"
)


def test_extract_filer_info_without_hon_title():
    # Before the fix, the regex required a literal "Hon." prefix, so a
    # filer whose name is rendered without it (e.g. a member newly seated
    # via special election) silently returned an empty name.
    name, state = extract_filer_info(FIELDS_NO_HON_TITLE)
    assert name == "Cleo Fields"
    assert state == "LA06"


def test_extract_filer_info_with_hon_title_is_unaffected():
    name, state = extract_filer_info(ALFORD_WITH_HON_TITLE)
    assert name == "Mark Alford"
    assert state == "MO04"
