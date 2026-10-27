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


def mark_filings_seen(filing_ids):
    """
    Record filing IDs as processed so future runs don't report them again.

    Callers must pass only filing IDs that were ACTUALLY fetched/parsed
    successfully (e.g. parse_all_filings()'s returned successful_filing_ids),
    never the raw list of everything the scrapers found — a filing whose
    report download failed (network error, bot-detection block, etc.) must
    stay unseen so it gets retried on the next run instead of being
    silently and permanently lost.
    """
    seen = load_seen_trades()
    seen.update(filing_ids)
    save_seen_trades(seen)


def run():
    log("Pipeline started")

    filings_count = 0
    trades_flagged = 0
    email_sent = False
    error_occurred = False

    def finish():
        if not email_sent and os.getenv("GITHUB_ACTIONS"):
            print("ERROR: Email was not sent. Failing CI run.")
            raise SystemExit(1)

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
        try:
            print("\n" + "=" * 60)
            print("STEP 5: Sending daily email report")
            print("=" * 60)
            email_sent = send_report([], no_new_filings=True)
        except Exception as e:
            log(f"ERROR in emailer: {e}")
            error_occurred = True
            email_sent = False

        email_status = "sent" if email_sent else "FAILED"
        status = "SUCCESS" if not error_occurred else "PARTIAL"
        log(f"Pipeline {status} — 0 new filings, email {email_status}")
        finish()
        return

    # ─── STEP 2: PARSE ───
    trades = []
    parsed_filing_ids = []
    try:
        print("\n" + "=" * 60)
        print("STEP 2: Parsing trade details from filings")
        print("=" * 60)
        trades, parsed_filing_ids = parse_all_filings(all_filings)
    except Exception as e:
        log(f"ERROR in parser: {e}")
        error_occurred = True

    if not trades:
        try:
            print("\n" + "=" * 60)
            print("STEP 5: Sending daily email report")
            print("=" * 60)
            email_sent = send_report([], total_filings=filings_count)
        except Exception as e:
            log(f"ERROR in emailer: {e}")
            error_occurred = True
            email_sent = False

        # Mark only the filings that were actually fetched/parsed (even
        # though none of them produced trades) — a filing that failed to
        # download must NOT be marked seen just because it happened to
        # land in a batch alongside filings that were genuinely empty.
        if email_sent and not error_occurred and parsed_filing_ids:
            mark_filings_seen(parsed_filing_ids)

        email_status = "sent" if email_sent else "FAILED"
        status = "SUCCESS" if not error_occurred else "PARTIAL"
        log(f"Pipeline {status} — {filings_count} filings, 0 trades parsed, email {email_status}")
        finish()
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
    # failed email means they get picked up again on the next run.
    # Use parsed_filing_ids (not all_filings) — a filing whose report
    # download failed (network error, bot-detection block, etc.) must
    # stay unseen so it's retried, instead of being lumped in with
    # filings that were successfully processed.
    if email_sent and scored:
        mark_filings_seen(parsed_filing_ids)

    status = "SUCCESS" if not error_occurred else "PARTIAL"
    email_status = "sent" if email_sent else "FAILED"
    log(f"Pipeline {status} — {filings_count} filings, "
        f"{len(trades)} trades parsed, {trades_flagged} flagged, "
        f"email {email_status}")

    print("\n" + "=" * 60)
    print("Pipeline complete.")
    print("=" * 60)
    finish()


if __name__ == "__main__":
    run()
