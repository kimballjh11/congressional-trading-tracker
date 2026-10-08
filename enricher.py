# enricher.py — Add committee and stock data to parsed trades
# Pulls committee assignments from:
#   - House: clerk.house.gov MemberData XML
#   - Senate: senate.gov committee assignments page
# Stock info (price, sector, industry) from Yahoo Finance.

import requests
import re
import json
import os
import xml.etree.ElementTree as ET
import yfinance as yf

from config import (
    PARSED_TRADES_FILE, ENRICHED_TRADES_FILE, DATA_DIR,
    HOUSE_MEMBER_XML, SENATE_ASSIGNMENTS_URL, REQUEST_TIMEOUT,
)


# ─── HOUSE COMMITTEE LOOKUP ───

def fetch_house_committee_data():
    """
    Download the House Clerk's MemberData XML and build a member → committees map.
    Key is "LastName, FirstName|StateDistrict".
    """
    print("Fetching House committee data from clerk.house.gov...")
    response = requests.get(HOUSE_MEMBER_XML, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        print(f"  Failed to fetch House committee data: {response.status_code}")
        return {}

    root = ET.fromstring(response.content)

    # Build code → name map
    comcode_to_name = {}
    committees_section = root.find("committees")
    if committees_section is not None:
        for comm in committees_section.findall(".//committee"):
            code = comm.get("comcode", "")
            name_el = comm.find("committee-fullname")
            if code and name_el is not None and name_el.text:
                comcode_to_name[code] = name_el.text

    # Build member → committees map
    member_committees = {}
    members_section = root.find("members")
    if members_section is not None:
        for member in members_section.findall("member"):
            name_el = member.find(".//namelist")
            sd_el = member.find("statedistrict")
            if name_el is None or sd_el is None:
                continue
            if name_el.text is None or sd_el.text is None:
                continue

            name = name_el.text.strip()
            sd = sd_el.text.strip()
            key = f"{name}|{sd}"

            comm_assignments = member.find("committee-assignments")
            if comm_assignments is None:
                continue

            comms = []
            for c in comm_assignments.findall("committee"):
                code = c.get("comcode", "")
                comm_name = comcode_to_name.get(code, code)
                comms.append(comm_name)

            member_committees[key] = comms

    print(f"  Loaded {len(member_committees)} House members")
    return member_committees


# ─── SENATE COMMITTEE LOOKUP ───

def fetch_senate_committee_data():
    """
    Scrape Senate committee assignments from senate.gov.
    Each senator has an anchor block with their name and committee links.
    Key is "LastName, FirstName|ST" (state abbreviation).
    """
    print("Fetching Senate committee data from senate.gov...")
    response = requests.get(
        SENATE_ASSIGNMENTS_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        print(f"  Failed to fetch Senate committee data: {response.status_code}")
        return {}

    html = response.text
    member_committees = {}

    # Split by senator anchor points: <a name="LastNameST">
    # Then extract senator name and committee links from each block
    blocks = re.split(r'<a\s+name="(\w+)">', html)

    for i in range(1, len(blocks) - 1, 2):
        anchor = blocks[i]
        content = blocks[i + 1]

        # Extract senator name and state from the content
        name_match = re.search(
            r'href="[^"]*">([^<]+)</a>\s*\(([RDI])-([A-Z]{2})\)',
            content[:500],
        )
        if not name_match:
            continue

        full_name = name_match.group(1).strip()
        state = name_match.group(3)

        # Extract committee names from links
        comms = re.findall(
            r'committee_memberships[^>]*>([^<]+)</a>',
            content,
            re.IGNORECASE,
        )

        key = f"{full_name}|{state}"
        member_committees[key] = comms

    print(f"  Loaded {len(member_committees)} senators")
    return member_committees


# ─── UNIFIED COMMITTEE LOOKUP ───

def find_committees_for_member(house_comms, senate_comms, representative, state_district, chamber=""):
    """
    Look up committees for a member across both chambers.
    Tries exact match first, then falls back to last-name matching.

    The lookup is scoped to the trade's own chamber whenever it's known
    (House trades only search house_comms, Senate trades only search
    senate_comms). This matters most for the last-name-only fallback:
    several last names are shared by a House member and a Senator at once
    (e.g. "Scott", "Cruz"), and searching both chambers' dicts together
    risks silently attributing one member's committee assignments to a
    different member in the other chamber. If chamber is unknown/blank,
    both chambers are searched as before (best-effort).
    """
    if chamber == "House":
        candidates = house_comms
    elif chamber == "Senate":
        candidates = senate_comms
    else:
        candidates = {}
        candidates.update(house_comms)
        candidates.update(senate_comms)

    # Try exact state_district match
    for key, comms in candidates.items():
        name_part, sd_part = key.split("|", 1)
        if sd_part == state_district and name_part.split(",")[0].lower() in representative.lower():
            return comms

    # Try matching Senate by state abbreviation (first 2 chars of state_district).
    # Only relevant for Senate trades (or when chamber is unknown) — a House
    # trade's state_district (e.g. "GA12") sharing its first 2 chars with a
    # senator's state is a coincidence, not a match.
    if chamber != "House":
        state_abbr = state_district[:2] if state_district else ""
        if state_abbr:
            for key, comms in senate_comms.items():
                name_part, sd_part = key.split("|", 1)
                if sd_part == state_abbr and name_part.split(",")[0].lower() in representative.lower():
                    return comms

    # Fallback: match on last name only, scoped to the same chamber
    last_name = representative.split(",")[0].strip().split()[-1].lower()
    for key, comms in candidates.items():
        name_part = key.split("|")[0]
        if name_part.split(",")[0].strip().lower() == last_name:
            return comms

    return []


# ─── STOCK DATA LOOKUP ───

def fetch_stock_info(ticker):
    """
    Use yfinance to get current price, sector, and industry for a ticker.
    Returns a dict with the data, or empty values if lookup fails.
    """
    if not ticker:
        return {"current_price": None, "sector": "", "industry": ""}

    try:
        t = yf.Ticker(ticker)
        info = t.info
        return {
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
        }
    except Exception as e:
        print(f"  Failed to fetch stock info for {ticker}: {e}")
        return {"current_price": None, "sector": "", "industry": ""}


# ─── MAIN ENRICHMENT ───

def enrich_trades():
    """
    Load parsed trades, add committee and stock data, save to enriched file.
    """
    if not os.path.exists(PARSED_TRADES_FILE):
        print(f"No parsed trades found at {PARSED_TRADES_FILE}. Run parser.py first.")
        return []

    with open(PARSED_TRADES_FILE, "r") as f:
        trades = json.load(f)

    print(f"Loaded {len(trades)} parsed trade(s)\n")

    # Fetch committee data for both chambers
    house_comms = fetch_house_committee_data()
    senate_comms = fetch_senate_committee_data()

    # Cache stock lookups
    stock_cache = {}
    tickers = set(t.get("ticker", "") for t in trades if t.get("ticker"))
    print(f"\nLooking up stock data for {len(tickers)} ticker(s)...")

    for ticker in tickers:
        print(f"  Fetching {ticker}...")
        stock_cache[ticker] = fetch_stock_info(ticker)

    # Enrich each trade
    print(f"\nEnriching {len(trades)} trade(s)...")
    enriched = []
    for trade in trades:
        # Add committee data
        committees = find_committees_for_member(
            house_comms,
            senate_comms,
            trade.get("representative", ""),
            trade.get("state_district", ""),
            trade.get("chamber", ""),
        )
        trade["committees"] = committees

        # Add stock data
        ticker = trade.get("ticker", "")
        stock_info = stock_cache.get(ticker, {"current_price": None, "sector": "", "industry": ""})
        trade["current_price"] = stock_info["current_price"]
        trade["sector"] = stock_info["sector"]
        trade["industry"] = stock_info["industry"]

        enriched.append(trade)

    # Save
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ENRICHED_TRADES_FILE, "w") as f:
        json.dump(enriched, f, indent=2)

    print(f"\nSaved {len(enriched)} enriched trade(s) to {ENRICHED_TRADES_FILE}")
    return enriched


# ─── RUN DIRECTLY FOR TESTING ───
if __name__ == "__main__":
    trades = enrich_trades()

    print("\n" + "=" * 60)
    print("ENRICHED TRADES")
    print("=" * 60)

    for t in trades:
        print(f"\n  Member:      {t['representative']}")
        print(f"  Committees:  {', '.join(t['committees']) if t['committees'] else '—'}")
        print(f"  Asset:       {t['asset']}")
        print(f"  Ticker:      {t['ticker'] or '—'}")
        print(f"  Type:        {t['transaction_type']}")
        print(f"  Amount:      {t['amount']}")
        print(f"  Date:        {t['transaction_date']}")
        if t.get("current_price"):
            print(f"  Price Now:   ${t['current_price']:.2f}")
        print(f"  Sector:      {t['sector'] or '—'}")
        print(f"  Industry:    {t['industry'] or '—'}")
