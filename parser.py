# parser.py — Extract trade details from House PTR PDFs and Senate PTR HTML reports
# Downloads each filing and parses out individual trades.

import requests
import pdfplumber
import re
import json
import os
import io
from bs4 import BeautifulSoup

from config import PARSED_TRADES_FILE, DATA_DIR


def download_pdf(url):
    """Download a PDF and return it as a bytes buffer."""
    response = requests.get(url)
    if response.status_code != 200:
        print(f"  Failed to download: {url} (status {response.status_code})")
        return None
    return io.BytesIO(response.content)


def extract_text_from_pdf(pdf_bytes):
    """Extract all text from a PDF, combining all pages."""
    text = ""
    with pdfplumber.open(pdf_bytes) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


def extract_filer_info(text):
    """Pull the filer's name and state/district from the PDF header."""
    name = ""
    state = ""

    name_match = re.search(r"Name:\s*Hon\.?\s*(.+)", text)
    if name_match:
        name = name_match.group(1).strip()

    state_match = re.search(r"State/District:\s*(\S+)", text)
    if state_match:
        state = state_match.group(1).strip()

    return name, state


def parse_trades_from_text(text):
    """
    Parse individual trades from the PDF text.

    Each trade block starts with an owner code (SP, JT, DC, etc.)
    followed by the asset name, transaction type, dates, and amount.
    """
    trades = []

    # The transaction section sits between the table header and the footnote
    header_match = re.search(r"\$200\?\n", text)
    footer_match = re.search(r"\* For the complete list", text)

    if not header_match:
        return trades

    start = header_match.end()
    end = footer_match.start() if footer_match else len(text)
    trade_section = text[start:end].strip()

    # Split into trade blocks. Each trade starts with an owner code
    # (1-2 uppercase letters) at the start of a line, followed by the asset.
    # "Filing Status:" lines mark metadata that follows each trade.
    # We split on owner codes that start a new trade entry.
    trade_blocks = re.split(r"\n(?=[A-Z]{1,2} [A-Z])", trade_section)

    for block in trade_blocks:
        block = block.strip()
        if not block:
            continue

        trade = parse_single_trade(block)
        if trade:
            trades.append(trade)

    return trades


def parse_single_trade(block):
    """
    Parse a single trade block into structured data.

    Example block:
      SP Ferguson Enterprises Inc. Common P 12/12/2025 01/06/2026 $15,001 -
      Stock (FERG) [ST] $50,000
      Filing Status: New
      Subholding Of: R.W. Allen & Associates, Inc. > RWA&A - Securities
    """
    trade = {
        "owner": "",
        "asset": "",
        "ticker": "",
        "transaction_type": "",
        "transaction_date": "",
        "notification_date": "",
        "amount": "",
        "description": "",
    }

    # Extract owner code (first 1-2 uppercase letters)
    owner_match = re.match(r"^([A-Z]{1,2})\s+", block)
    if owner_match:
        trade["owner"] = owner_match.group(1)
        block = block[owner_match.end():]

    # Extract description if present
    desc_match = re.search(r"D\x00*\w*\s*:\s*(.+?)(?:\n|$)", block)
    if not desc_match:
        desc_match = re.search(r"D          :\s*(.+?)(?:\n|$)", block)
    if desc_match:
        trade["description"] = desc_match.group(1).strip()

    # Extract ticker symbol from parentheses, e.g., (FERG), (NFLX), (STT)
    ticker_match = re.search(r"\(([A-Z]{1,5})\)", block)
    if ticker_match:
        trade["ticker"] = ticker_match.group(1)

    # Extract dates (MM/DD/YYYY format)
    dates = re.findall(r"\d{2}/\d{2}/\d{4}", block)
    if len(dates) >= 1:
        trade["transaction_date"] = dates[0]
    if len(dates) >= 2:
        trade["notification_date"] = dates[1]

    # Extract amount range (e.g., "$15,001 - $50,000" or "$1,001 - $15,000")
    # The range often wraps across lines with other text in between, like:
    #   "$15,001 -\nStock (FERG) [ST] $50,000"
    # So we find all dollar amounts and take the first two as the range.
    dollar_amounts = re.findall(r"\$[\d,]+", block)
    if len(dollar_amounts) >= 2:
        trade["amount"] = f"{dollar_amounts[0]} - {dollar_amounts[1]}"
    elif len(dollar_amounts) == 1:
        trade["amount"] = dollar_amounts[0]

    # Extract transaction type: P (purchase), S (sale), S (partial), E (exchange)
    # It appears right before the first date
    if dates:
        # Look for a single letter (P, S, E) right before the date
        tx_match = re.search(r"\b([PSE])\s+(?:\(partial\)\s+)?" + re.escape(dates[0]), block)
        if tx_match:
            tx_code = tx_match.group(1)
            is_partial = "(partial)" in block[tx_match.start():tx_match.start() + 20]
            if tx_code == "P":
                trade["transaction_type"] = "Purchase"
            elif tx_code == "S" and is_partial:
                trade["transaction_type"] = "Sale (partial)"
            elif tx_code == "S":
                trade["transaction_type"] = "Sale"
            elif tx_code == "E":
                trade["transaction_type"] = "Exchange"
            else:
                trade["transaction_type"] = tx_code

    # Extract asset name — everything from start of block up to the transaction type letter
    # before the date. We grab the text, remove the ticker bracket, and clean it up.
    if dates:
        asset_section = block.split(dates[0])[0]
        # Remove transaction type letter at the end
        asset_section = re.sub(r"\s+[PSE]\s*(\(partial\)\s*)?$", "", asset_section)
        # Remove bracket codes like [ST], [GS], [OP]
        asset_section = re.sub(r"\[.{1,4}\]", "", asset_section)
        # Remove newlines and collapse whitespace
        asset_section = re.sub(r"\s+", " ", asset_section).strip()
        trade["asset"] = asset_section

    return trade


def extract_cell_text(cell):
    """
    Extract the meaningful text from a Senate PTR table cell.

    Real Senate reports render some cells (Ticker, Comment) with a literal
    "--" placeholder followed by a <br/> and the actual value (e.g. an
    auto-linked ticker for an Exchange transaction's received security), and
    render others (Asset Name, for Exchange transactions with a given-up and
    a received security) as multiple lines separated only by a <br/>. Using
    BeautifulSoup's default get_text(strip=True) has no separator between
    those lines, so it silently concatenates them with no space at all (e.g.
    "--AMCR" or "...(Exchanged)Amcor plc..."). Confirmed live against a real
    Senate PTR report (Wyden, filed 2026-08-08): the correct values are
    "AMCR" (dropping the "--" placeholder entirely) and "...(Exchanged)
    Amcor plc..." (with the lines joined by a space), matching independent
    third-party parses of the same report.
    """
    parts = [s.strip() for s in cell.stripped_strings]
    parts = [p for p in parts if p and p != "--"]
    return " ".join(parts)


def parse_senate_html(html, filing):
    """
    Parse a Senate PTR HTML report page.
    Senate reports have an HTML table with trade details.
    Returns a list of trade dicts.
    """
    trades = []
    soup = BeautifulSoup(html, "html.parser")

    # Senate PTR tables typically have columns:
    # Transaction Date, Owner, Ticker, Asset Name, Asset Type, Type, Amount, Comment
    tables = soup.find_all("table")

    for table in tables:
        headers = []
        for th in table.find_all("th"):
            headers.append(th.get_text(strip=True).lower())

        if not headers:
            # Try first row as headers
            first_row = table.find("tr")
            if first_row:
                for td in first_row.find_all("td"):
                    headers.append(td.get_text(strip=True).lower())

        # Check if this looks like a transaction table
        has_transaction_cols = any(
            kw in " ".join(headers)
            for kw in ["transaction", "asset", "ticker", "amount", "type"]
        )
        if not has_transaction_cols:
            continue

        rows = table.find_all("tr")[1:]  # Skip header row
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            cell_texts = [extract_cell_text(c) for c in cells]

            # Map cells to fields based on header positions
            trade = {
                "owner": "",
                "asset": "",
                "ticker": "",
                "transaction_type": "",
                "transaction_date": "",
                "notification_date": filing.get("date_submitted", ""),
                "amount": "",
                "description": "",
            }

            for i, header in enumerate(headers):
                if i >= len(cell_texts):
                    break
                val = cell_texts[i]

                if "date" in header and "transaction" in header:
                    trade["transaction_date"] = val
                elif "owner" in header:
                    trade["owner"] = val
                elif "ticker" in header:
                    trade["ticker"] = val
                elif "asset" in header and "type" not in header:
                    trade["asset"] = val
                elif header in ("type", "transaction type"):
                    # Normalize transaction type
                    vl = val.lower()
                    if "purchase" in vl:
                        trade["transaction_type"] = "Purchase"
                    elif "sale" in vl and "partial" in vl:
                        trade["transaction_type"] = "Sale (partial)"
                    elif "sale" in vl:
                        trade["transaction_type"] = "Sale"
                    elif "exchange" in vl:
                        trade["transaction_type"] = "Exchange"
                    else:
                        trade["transaction_type"] = val
                elif "amount" in header:
                    trade["amount"] = val
                elif "comment" in header or "description" in header:
                    trade["description"] = val

            # Only keep rows that look like actual trades
            if trade["asset"] or trade["ticker"]:
                trades.append(trade)

    return trades


def parse_filing(filing):
    """
    Download and parse a single PTR filing.
    Routes to PDF parser (House) or HTML parser (Senate) based on chamber.
    Returns a list of trades found.
    """
    chamber = filing.get("chamber", "House")
    print(f"  Parsing {filing['representative']} — {filing['filing_id']}...")

    if chamber == "Senate":
        return parse_senate_filing(filing)
    else:
        return parse_house_filing(filing)


def parse_house_filing(filing):
    """Parse a House PTR filing (PDF format)."""
    pdf_bytes = download_pdf(filing["pdf_url"])
    if not pdf_bytes:
        return []

    text = extract_text_from_pdf(pdf_bytes)
    if not text:
        print(f"  No text extracted from PDF")
        return []

    name, state = extract_filer_info(text)
    raw_trades = parse_trades_from_text(text)

    trades = []
    for t in raw_trades:
        t["representative"] = name or filing.get("representative", "Unknown")
        t["state_district"] = state or filing.get("state_district", "")
        t["filing_id"] = filing["filing_id"]
        t["pdf_url"] = filing["pdf_url"]
        t["chamber"] = "House"
        trades.append(t)

    return trades


def parse_senate_filing(filing):
    """Parse a Senate PTR filing (HTML format)."""
    url = filing.get("pdf_url", "")
    if not url:
        return []

    response = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })
    if response.status_code != 200:
        print(f"  Failed to download Senate report: {url} (status {response.status_code})")
        return []

    raw_trades = parse_senate_html(response.text, filing)

    trades = []
    for t in raw_trades:
        t["representative"] = filing.get("representative", "Unknown")
        t["state_district"] = filing.get("state_district", "")
        t["filing_id"] = filing["filing_id"]
        t["pdf_url"] = url
        t["chamber"] = "Senate"
        trades.append(t)

    return trades


def parse_all_filings(filings):
    """
    Parse a list of filings and return all trades found.
    Saves results to data/parsed_trades.json.
    """
    print(f"Parsing {len(filings)} filing(s)...\n")

    all_trades = []
    for filing in filings:
        trades = parse_filing(filing)
        all_trades.extend(trades)

    # Save to disk
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PARSED_TRADES_FILE, "w") as f:
        json.dump(all_trades, f, indent=2)

    print(f"\nTotal trades parsed: {len(all_trades)}")
    print(f"Saved to {PARSED_TRADES_FILE}")
    return all_trades


# ─── RUN DIRECTLY FOR TESTING ───
if __name__ == "__main__":
    # Test with a few real filings from the scraper
    test_filings = [
        {
            "representative": "Allen, Richard W.",
            "state_district": "GA12",
            "filing_id": "20033751",
            "pdf_url": "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20033751.pdf",
        },
        {
            "representative": "Beyer, Donald Sternoff Jr.",
            "state_district": "VA08",
            "filing_id": "20033714",
            "pdf_url": "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20033714.pdf",
        },
        {
            "representative": "Auchincloss, Jake",
            "state_district": "MA04",
            "filing_id": "20034024",
            "pdf_url": "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20034024.pdf",
        },
    ]

    trades = parse_all_filings(test_filings)

    print("\n" + "=" * 60)
    print("PARSED TRADES")
    print("=" * 60)

    for t in trades:
        print(f"\n  Member:      {t['representative']}")
        print(f"  Asset:       {t['asset']}")
        print(f"  Ticker:      {t['ticker'] or '—'}")
        print(f"  Type:        {t['transaction_type']}")
        print(f"  Amount:      {t['amount']}")
        print(f"  Date:        {t['transaction_date']}")
        print(f"  Description: {t['description'] or '—'}")
        print(f"  PDF:         {t['pdf_url']}")
