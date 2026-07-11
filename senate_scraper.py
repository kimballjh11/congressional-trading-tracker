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

from config import SEEN_TRADES_FILE, SENATE_EFDS_URL, DATA_DIR, REQUEST_TIMEOUT

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
    try:
        resp = session.get(f"{BASE_URL}/search/home/", timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"  Failed to connect to Senate EFDS: {e}")
        return None
    if resp.status_code != 200:
        print(f"  Failed to load Senate EFDS: status {resp.status_code}")
        return None

    # Extract CSRF token from the form
    csrf_match = re.search(
        r'csrfmiddlewaretoken"\s+value="([^"]+)"', resp.text
    )
    if not csrf_match:
        print("  Could not find CSRF token on Senate EFDS page")
        return None

    csrf_token = csrf_match.group(1)

    # Step 2: Accept the usage agreement
    try:
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
    except requests.RequestException as e:
        print(f"  Failed to accept Senate EFDS usage agreement: {e}")
        return None

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
        start_date = (datetime.now() - timedelta(days=45)).strftime("%m/%d/%Y")
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

    try:
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
    except requests.RequestException as e:
        print(f"  Search failed: {e}")
        return []

    if resp.status_code != 200:
        print(f"  Search failed: status {resp.status_code}")
        return []

    # Check if we got the maintenance page instead of JSON
    if "Site Under Maintenance" in resp.text:
        print("  Senate EFDS search backend is under maintenance.")
        print("  The front-end loads but the search API is temporarily down.")
        print("  Senate filings will be skipped for this run.")
        return []

    try:
        result = resp.json()
    except (json.JSONDecodeError, ValueError):
        print("  Failed to parse search results as JSON")
        return []

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

        try:
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
        except requests.RequestException as e:
            print(f"  Pagination request failed: {e}")
            break

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
            try:
                return set(json.load(f))
            except (json.JSONDecodeError, ValueError):
                print(f"  Warning: {SEEN_TRADES_FILE} is corrupt or unreadable; starting with an empty seen set.")
                return set()
    return set()


def save_seen_trades(seen):
    """Save seen filing IDs."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEEN_TRADES_FILE, "w") as f:
        json.dump(list(seen), f)


def get_new_senate_trades():
    """
    MAIN FUNCTION — Fetch new Senate PTR filings.
    Returns a list of new filing dicts.
    """
    seen = load_seen_trades()
    senate_seen = {s for s in seen if s.startswith("senate_")}
    print(f"Previously seen Senate filings: {len(senate_seen)}")

    session = create_session()
    if not session:
        print("Failed to establish Senate EFDS session")
        return []

    filings = search_ptr_filings(session)

    new_filings = []
    for filing in filings:
        if filing["filing_id"] not in seen:
            new_filings.append(filing)
            seen.add(filing["filing_id"])

    save_seen_trades(seen)

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
