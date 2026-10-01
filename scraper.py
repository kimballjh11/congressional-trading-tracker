# scraper.py — Phase 1: Detect new congressional trade filings
# Scrapes the official House Clerk Financial Disclosure site
# to find new Periodic Transaction Reports (PTRs).
# No API key needed — this is public government data.

import requests
import re
import json
import os
from datetime import datetime

from config import SEEN_TRADES_FILE, HOUSE_CLERK_URL, DATA_DIR, REQUEST_TIMEOUT


def load_seen_trades():
    """
    Load the set of filing IDs we've already processed.
    If the file doesn't exist yet (first run), return an empty set.
    """
    if os.path.exists(SEEN_TRADES_FILE):
        with open(SEEN_TRADES_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_trades(seen):
    """
    Save the updated set of seen filing IDs to disk.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEEN_TRADES_FILE, "w") as f:
        json.dump(list(seen), f)


def fetch_house_filings(year=None):
    """
    Scrape the House Clerk's public disclosure search page.
    Returns a list of PTR filings with member name, state, and PDF link.
    """
    if year is None:
        year = datetime.now().year

    print(f"Fetching House PTR filings for {year}...")

    data = {
        "LastName": "",
        "FilingYear": str(year),
        "State": "",
        "District": "",
        "fromDate": "",
        "toDate": "",
    }

    response = requests.post(HOUSE_CLERK_URL, data=data, timeout=REQUEST_TIMEOUT)

    if response.status_code != 200:
        raise RuntimeError(f"House Clerk returned status {response.status_code}")

    html = response.text
    filings = parse_filings_html(html)
    print(f"Total PTR filings found: {len(filings)}")
    return filings


def parse_filings_html(html):
    """
    Parse the HTML table returned by the House Clerk search.
    Each row has: Name, State/District, Year, Filing Type, PDF link.
    """
    filings = []

    rows = re.findall(r'<tr[^>]*role="row"[^>]*>(.*?)</tr>', html, re.DOTALL)

    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        href = re.findall(r'href="([^"]+)"', row)

        if len(cells) < 4 or not href:
            continue

        # Clean HTML tags from cell contents
        name = re.sub(r"<[^>]+>", "", cells[0]).strip()
        state_district = re.sub(r"<[^>]+>", "", cells[1]).strip()
        year = re.sub(r"<[^>]+>", "", cells[2]).strip()
        filing_type = re.sub(r"<[^>]+>", "", cells[3]).strip()

        # Only keep PTR filings (Periodic Transaction Reports = trades)
        if "PTR" not in filing_type:
            continue

        # Extract the filing ID from the PDF path (e.g. 20033751 from ptr-pdfs/2026/20033751.pdf)
        pdf_path = href[0]
        filing_id_match = re.search(r"(\d{8})\.pdf", pdf_path)
        raw_id = filing_id_match.group(1) if filing_id_match else pdf_path
        filing_id = f"house_{raw_id}"

        # Clean up the name (remove "Hon.." artifacts)
        name = re.sub(r"Hon\.+\s*", "", name).strip()

        filings.append(
            {
                "representative": name,
                "state_district": state_district,
                "year": year,
                "filing_type": filing_type,
                "filing_id": filing_id,
                "pdf_url": f"https://disclosures-clerk.house.gov/{pdf_path}",
                "chamber": "House",
            }
        )

    return filings


def get_new_trades():
    """
    MAIN FUNCTION — This is what main.py will call.
    1. Fetch all PTR filings from the House Clerk
    2. Compare against what we've already seen
    3. Return only the new ones
    (main.py marks them seen once they've been reported)
    """
    seen = load_seen_trades()
    print(f"Previously seen filings: {len(seen)}")

    filings = fetch_house_filings()
    if not filings:
        return []

    new_filings = []
    for filing in filings:
        if filing["filing_id"] not in seen:
            new_filings.append(filing)

    print(f"New filings found: {len(new_filings)}")
    return new_filings


# ─── RUN DIRECTLY FOR TESTING ───
if __name__ == "__main__":
    filings = get_new_trades()

    print("\n" + "=" * 60)
    print("SAMPLE NEW FILINGS")
    print("=" * 60)

    for filing in filings[:10]:
        print(f"\n  Name:        {filing['representative']}")
        print(f"  State:       {filing['state_district']}")
        print(f"  Type:        {filing['filing_type']}")
        print(f"  PDF:         {filing['pdf_url']}")

    print(f"\nTotal new filings: {len(filings)}")

    if not filings:
        print("\nNo new filings found. Delete data/seen_trades.json to reset.")
