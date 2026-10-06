# senate_scraper.py — Scrape Senate PTR filings from efdsearch.senate.gov
# The Senate's Electronic Financial Disclosure (eFD) search system uses:
#   1. A CSRF-protected agreement page at /search/home/
#   2. A DataTables server-side API at /search/report/data/
#
# NOTE: As of March 2026, the Senate search backend intermittently returns
# a "Site Under Maintenance" page. This scraper handles that gracefully
# and will work when the site is back up.

import requests
import re
import json
import os
from datetime import datetime, timedelta

from config import (
    SEEN_TRADES_FILE,
    SENATE_EFDS_URL,
    DATA_DIR,
    REQUEST_TIMEOUT,
    SENATE_SCAN_CURSOR_FILE,
    SENATE_DEFAULT_LOOKBACK_DAYS,
    SENATE_MAX_LOOKBACK_DAYS,
    SENATE_SCAN_OVERLAP_DAYS,
)

BASE_URL = SENATE_EFDS_URL
REPORT_TYPE_PTR = "11"  # Senate report type code for Periodic Transaction Reports


def create_session():
    """
    Create a requests session with browser-like headers
    and accept the Senate EFDS usage agreement.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
    })

    # Step 1: Load the home page to get CSRF token and cookies
    print("  Connecting to Senate EFDS...")
    resp = session.get(f"{BASE_URL}/search/home/", timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Senate EFDS home page returned status {resp.status_code}")

    # Extract CSRF token from the form
    csrf_match = re.search(
        r'csrfmiddlewaretoken"\s+value="([^"]+)"', resp.text
    )
    if not csrf_match:
        raise RuntimeError("Could not find CSRF token on Senate EFDS page")

    csrf_token = csrf_match.group(1)

    # Step 2: Accept the usage agreement
    resp = session.post(
        f"{BASE_URL}/search/home/",
        data={
            "prohibition_agreement": "1",
            "csrfmiddlewaretoken": csrf_token,
        },
        headers={
            "Referer": f"{BASE_URL}/search/home/",
            "Origin": BASE_URL,
        },
        timeout=REQUEST_TIMEOUT,
    )

    # The CSRF token for API calls comes from the cookie
    csrf_cookie = session.cookies.get("csrftoken", "")
    if not csrf_cookie:
        print("  Warning: No CSRF cookie received")

    print("  Session established")
    return session


def search_ptr_filings(session, start_date=None, end_date=None):
    """
    Search for PTR filings using the DataTables server-side API.
    Returns a list of filing dicts or empty list on failure.
    """
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=SENATE_DEFAULT_LOOKBACK_DAYS)).strftime("%m/%d/%Y")
    if end_date is None:
        end_date = datetime.now().strftime("%m/%d/%Y")

    csrf_cookie = session.cookies.get("csrftoken", "")

    print(f"  Searching PTR filings from {start_date} to {end_date}...")

    # DataTables server-side processing format
    data = {
        "draw": "1",
        "start": "0",
        "length": "100",
        "report_types": json.dumps([REPORT_TYPE_PTR]),
        "filer_types": "[]",
        "submitted_start_date": start_date,
        "submitted_end_date": end_date,
        "candidate_state": "",
        "senator_state": "",
        "office_id": "",
        "first_name": "",
        "last_name": "",
    }

    resp = session.post(
        f"{BASE_URL}/search/report/data/",
        data=data,
        headers={
            "Referer": f"{BASE_URL}/search/",
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": csrf_cookie,
        },
        timeout=REQUEST_TIMEOUT,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Senate EFDS search returned status {resp.status_code}")

    # Check if we got the maintenance page instead of JSON
    if "Site Under Maintenance" in resp.text:
        raise RuntimeError("Senate EFDS search backend is under maintenance")

    try:
        result = resp.json()
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError("Senate EFDS search results were not valid JSON")

    total = result.get("recordsTotal", 0)
    print(f"  Total PTR filings found: {total}")

    filings = []
    for row in result.get("data", []):
        filing = parse_search_row(row)
        if filing:
            filings.append(filing)

    # If there are more results, paginate
    while len(filings) < total:
        data["start"] = str(len(filings))
        data["draw"] = str(int(data["draw"]) + 1)

        resp = session.post(
            f"{BASE_URL}/search/report/data/",
            data=data,
            headers={
                "Referer": f"{BASE_URL}/search/",
                "Origin": BASE_URL,
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrf_cookie,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if resp.status_code != 200 or "Site Under Maintenance" in resp.text:
            break

        try:
            page_result = resp.json()
        except (json.JSONDecodeError, ValueError):
            break

        new_rows = page_result.get("data", [])
        if not new_rows:
            break

        for row in new_rows:
            filing = parse_search_row(row)
            if filing:
                filings.append(filing)

    return filings


def parse_search_row(row):
    """
    Parse a single row from the DataTables search results.
    The Senate API returns rows as lists of HTML strings:
    [first_name, last_name, office, report_type_with_link, date_submitted]
    """
    if not row or len(row) < 5:
        return None

    first_name = strip_html(row[0]).strip()
    last_name = strip_html(row[1]).strip()
    office = strip_html(row[2]).strip()
    report_cell = row[3]  # Contains the link to the report
    date_submitted = strip_html(row[4]).strip()

    # Extract the report URL from the HTML link
    href_match = re.search(r'href="([^"]+)"', report_cell)
    report_url = ""
    if href_match:
        path = href_match.group(1)
        if path.startswith("/"):
            report_url = f"{BASE_URL}{path}"
        else:
            report_url = path

    report_type = strip_html(report_cell).strip()

    # Only keep PTR filings
    if "Periodic Transaction Report" not in report_type and "PTR" not in report_type.upper():
        return None

    # Create a unique filing ID from the URL or combine fields
    filing_id = ""
    id_match = re.search(r"/([a-f0-9-]{36})/", report_url)
    if id_match:
        filing_id = id_match.group(1)
    else:
        filing_id = f"senate|{last_name}|{date_submitted}|{report_type}"

    name = f"{last_name}, {first_name}".strip(", ")

    return {
        "representative": name,
        "state_district": office,
        "year": datetime.now().strftime("%Y"),
        "filing_type": report_type,
        "filing_id": f"senate_{filing_id}",
        "pdf_url": report_url,  # Senate reports are usually HTML, not PDF
        "chamber": "Senate",
        "date_submitted": date_submitted,
    }


def strip_html(text):
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text) if text else ""


def load_seen_trades():
    """Load seen filing IDs, returns a set."""
    if os.path.exists(SEEN_TRADES_FILE):
        with open(SEEN_TRADES_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_trades(seen):
    """Save seen filing IDs."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEEN_TRADES_FILE, "w") as f:
        json.dump(list(seen), f)


def load_last_scan_date():
    """
    Load the date (as a datetime) through which the Senate search has been
    successfully scanned. Returns None if no cursor has been saved yet
    (e.g. the very first run, or a corrupt/missing cursor file).
    """
    if not os.path.exists(SENATE_SCAN_CURSOR_FILE):
        return None
    try:
        with open(SENATE_SCAN_CURSOR_FILE, "r") as f:
            data = json.load(f)
        return datetime.strptime(data["last_scan_date"], "%m/%d/%Y")
    except (json.JSONDecodeError, ValueError, KeyError, OSError):
        print("  Warning: could not read Senate scan cursor, falling back to default lookback")
        return None


def save_last_scan_date(date):
    """Persist the date through which the Senate search successfully ran."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SENATE_SCAN_CURSOR_FILE, "w") as f:
        json.dump({"last_scan_date": date.strftime("%m/%d/%Y")}, f)


def compute_search_start_date(now=None):
    """
    Decide how far back the Senate search should look.

    Normally this is just the default lookback window (matches the 45-day
    disclosure deadline). But if the last successful scan is older than
    that — e.g. the Senate EFDS search backend was down for a stretch — the
    window is extended back to the last successful scan (minus a small
    overlap buffer) so downtime doesn't cause PTRs outside the default
    window to be silently and permanently missed. The window is still
    capped at SENATE_MAX_LOOKBACK_DAYS so a stale or corrupt cursor can't
    trigger an effectively-unbounded scan.
    """
    if now is None:
        now = datetime.now()

    default_start = now - timedelta(days=SENATE_DEFAULT_LOOKBACK_DAYS)
    max_start = now - timedelta(days=SENATE_MAX_LOOKBACK_DAYS)

    last_scan = load_last_scan_date()
    if last_scan is None:
        return default_start

    cursor_start = last_scan - timedelta(days=SENATE_SCAN_OVERLAP_DAYS)
    # Use whichever is earlier (further back) between the default window
    # and the cursor, but never go back further than the max cap.
    start = min(default_start, cursor_start)
    start = max(start, max_start)
    return start


def get_new_senate_trades():
    """
    MAIN FUNCTION — Fetch new Senate PTR filings.
    Returns a list of new filing dicts.
    """
    seen = load_seen_trades()
    senate_seen = {s for s in seen if s.startswith("senate_")}
    print(f"Previously seen Senate filings: {len(senate_seen)}")

    session = create_session()

    now = datetime.now()
    start_date = compute_search_start_date(now).strftime("%m/%d/%Y")
    end_date = now.strftime("%m/%d/%Y")

    filings = search_ptr_filings(session, start_date=start_date, end_date=end_date)

    # Only advance the cursor once the search has actually completed above
    # without raising — on failure (bad status, maintenance page, bad JSON)
    # the caller's exception propagates up before this line, so the cursor
    # stays put and the next run retries the same (or wider) window instead
    # of silently narrowing it.
    save_last_scan_date(now)

    new_filings = []
    for filing in filings:
        if filing["filing_id"] not in seen:
            new_filings.append(filing)

    print(f"New Senate filings found: {len(new_filings)}")
    return new_filings


# ─── RUN DIRECTLY FOR TESTING ───
if __name__ == "__main__":
    filings = get_new_senate_trades()

    print("\n" + "=" * 60)
    print("SENATE PTR FILINGS")
    print("=" * 60)

    for f in filings[:10]:
        print(f"\n  Name:       {f['representative']}")
        print(f"  Office:     {f['state_district']}")
        print(f"  Type:       {f['filing_type']}")
        print(f"  Submitted:  {f['date_submitted']}")
        print(f"  Report:     {f['pdf_url']}")

    print(f"\nTotal new filings: {len(filings)}")

    if not filings:
        print("\nNo new Senate filings found (site may be under maintenance).")
