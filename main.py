# main.py — Full pipeline: scrape (House + Senate) → parse → enrich → score → email

import os
from datetime import datetime

from config import RUN_LOG_FILE, DATA_DIR
from scraper import get_new_trades
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


def run():
    log("Pipeline started")

    filings_count = 0
    trades_flagged = 0
    email_sent = False
    # Human-readable messages for any step that failed this run. Passed
    # through to send_report() so the email itself visibly flags a failed
    # run instead of looking identical to a genuinely quiet day — the run
    # log/CI status alone aren't enough since most users only ever see the
    # email, not data/run_log.txt or the GitHub Actions log.
    errors = []

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
        errors.append(f"House scraper failed: {e}")

    try:
        # ─── STEP 1b: SCRAPE SENATE ───
        print("\n" + "=" * 60)
        print("STEP 1b: Scraping new Senate PTR filings")
        print("=" * 60)
        senate_filings = get_new_senate_trades()
    except Exception as e:
        log(f"ERROR in Senate scraper: {e}")
        senate_filings = []
        errors.append(f"Senate scraper failed: {e}")

    all_filings = house_filings + senate_filings
    filings_count = len(all_filings)
    print(f"\nTotal new filings: {filings_count} "
          f"(House: {len(house_filings)}, Senate: {len(senate_filings)})")

    if not all_filings:
        try:
            print("\n" + "=" * 60)
            print("STEP 5: Sending daily email report")
            print("=" * 60)
            email_sent = send_report([], no_new_filings=True, errors=errors)
        except Exception as e:
            log(f"ERROR in emailer: {e}")
            errors.append(f"Emailer failed: {e}")
            email_sent = False

        email_status = "sent" if email_sent else "FAILED"
        status = "SUCCESS" if not errors else "PARTIAL"
        log(f"Pipeline {status} — 0 new filings, email {email_status}")
        finish()
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
        errors.append(f"Parser failed: {e}")

    if not trades:
        try:
            print("\n" + "=" * 60)
            print("STEP 5: Sending daily email report")
            print("=" * 60)
            email_sent = send_report([], total_filings=filings_count, errors=errors)
        except Exception as e:
            log(f"ERROR in emailer: {e}")
            errors.append(f"Emailer failed: {e}")
            email_sent = False

        email_status = "sent" if email_sent else "FAILED"
        status = "SUCCESS" if not errors else "PARTIAL"
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
        errors.append(f"Enricher failed: {e}")

    # ─── STEP 4: SCORE ───
    scored = []
    try:
        print("\n" + "=" * 60)
        print("STEP 4: Scoring trades for suspicion")
        print("=" * 60)
        scored = score_trades()
    except Exception as e:
        log(f"ERROR in scorer: {e}")
        errors.append(f"Scorer failed: {e}")

    trades_flagged = sum(1 for t in scored if t.get("score", 0) > 25)

    # ─── STEP 5: EMAIL ───
    try:
        print("\n" + "=" * 60)
        print("STEP 5: Sending email report")
        print("=" * 60)
        email_sent = send_report(scored, total_filings=filings_count, errors=errors)
    except Exception as e:
        log(f"ERROR in emailer: {e}")
        errors.append(f"Emailer failed: {e}")

    status = "SUCCESS" if not errors else "PARTIAL"
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
