# main.py — Full pipeline: scrape (House + Senate) → parse → enrich → score → email

import os
from datetime import datetime

from config import RUN_LOG_FILE, DATA_DIR
from scraper import get_new_trades, load_seen_trades, save_seen_trades
from senate_scraper import get_new_senate_trades
from parser import parse_all_filings
from enricher import enrich_trades
from scorer import score_trades
from emailer import send_report


def log(message):
    """Append a timestamped message to the run log."""
    os.makedirs(DATA_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    with open(RUN_LOG_FILE, "a") as f:
        f.write(line)
    print(line.strip())


def mark_filings_seen(filings):
    """Record filings as processed so future runs don't report them again."""
    seen = load_seen_trades()
    seen.update(f["filing_id"] for f in filings)
    save_seen_trades(seen)


def run():
    log("Pipeline started")

    filings_count = 0
    trades_flagged = 0
    email_sent = False
    error_occurred = False

    try:
        # ─── STEP 1: SCRAPE HOUSE ───
        print("=" * 60)
        print("STEP 1a: Scraping new House PTR filings")
        print("=" * 60)
        house_filings = get_new_trades()
    except Exception as e:
        log(f"ERROR in House scraper: {e}")
        house_filings = []
        error_occurred = True

    try:
        # ─── STEP 1b: SCRAPE SENATE ───
        print("\n" + "=" * 60)
        print("STEP 1b: Scraping new Senate PTR filings")
        print("=" * 60)
        senate_filings = get_new_senate_trades()
    except Exception as e:
        log(f"ERROR in Senate scraper: {e}")
        senate_filings = []
        error_occurred = True

    all_filings = house_filings + senate_filings
    filings_count = len(all_filings)
    print(f"\nTotal new filings: {filings_count} "
          f"(House: {len(house_filings)}, Senate: {len(senate_filings)})")

    if not all_filings:
        suffix = " (scraper errors above)" if error_occurred else ""
        log(f"Pipeline finished — no new filings found{suffix}")
        return

    # ─── STEP 2: PARSE ───
    trades = []
    try:
        print("\n" + "=" * 60)
        print("STEP 2: Parsing trade details from filings")
        print("=" * 60)
        trades = parse_all_filings(all_filings)
    except Exception as e:
        log(f"ERROR in parser: {e}")
        error_occurred = True

    if not trades:
        if not error_occurred:
            mark_filings_seen(all_filings)
        log(f"Pipeline finished — {filings_count} filings, 0 trades parsed")
        return

    # ─── STEP 3: ENRICH ───
    try:
        print("\n" + "=" * 60)
        print("STEP 3: Enriching with committee and stock data")
        print("=" * 60)
        enrich_trades()
    except Exception as e:
        log(f"ERROR in enricher: {e}")
        error_occurred = True

    # ─── STEP 4: SCORE ───
    scored = []
    try:
        print("\n" + "=" * 60)
        print("STEP 4: Scoring trades for suspicion")
        print("=" * 60)
        scored = score_trades()
    except Exception as e:
        log(f"ERROR in scorer: {e}")
        error_occurred = True

    trades_flagged = sum(1 for t in scored if t.get("score", 0) > 25)

    # ─── STEP 5: EMAIL ───
    try:
        print("\n" + "=" * 60)
        print("STEP 5: Sending email report")
        print("=" * 60)
        email_sent = send_report(scored, total_filings=filings_count)
    except Exception as e:
        log(f"ERROR in emailer: {e}")
        error_occurred = True

    # Only mark filings seen once the report went out, so a crash or
    # failed email means they get picked up again on the next run
    if email_sent:
        mark_filings_seen(all_filings)

    status = "SUCCESS" if not error_occurred else "PARTIAL"
    email_status = "sent" if email_sent else "FAILED"
    log(f"Pipeline {status} — {filings_count} filings, "
        f"{len(trades)} trades parsed, {trades_flagged} flagged, "
        f"email {email_status}")

    print("\n" + "=" * 60)
    print("Pipeline complete.")
    print("=" * 60)


if __name__ == "__main__":
    run()
