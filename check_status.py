# check_status.py — Quick health check for the trading pipeline
# Shows: last successful run, consecutive run days, missed days in last 7

import os
import re
from datetime import datetime, timedelta

from config import RUN_LOG_FILE


def parse_run_dates():
    """Extract all dates where the pipeline started from the run log."""
    if not os.path.exists(RUN_LOG_FILE):
        return []

    dates = set()
    with open(RUN_LOG_FILE, "r") as f:
        for line in f:
            match = re.match(r"\[(\d{4}-\d{2}-\d{2})", line)
            if match and "Pipeline started" in line:
                dates.add(match.group(1))

    return sorted(dates)


def get_last_result():
    """Get the most recent pipeline result line."""
    if not os.path.exists(RUN_LOG_FILE):
        return None

    with open(RUN_LOG_FILE, "r") as f:
        lines = f.readlines()

    for line in reversed(lines):
        if "Pipeline" in line and ("SUCCESS" in line or "PARTIAL" in line or "finished" in line):
            return line.strip()

    return None


def check_status():
    run_dates = parse_run_dates()
    today = datetime.now().strftime("%Y-%m-%d")

    print("=" * 50)
    print("PIPELINE HEALTH CHECK")
    print("=" * 50)

    if not run_dates:
        print("\nNo runs recorded yet.")
        print(f"Run log: {os.path.abspath(RUN_LOG_FILE)}")
        return

    # Last run
    last_date = run_dates[-1]
    days_ago = (datetime.now() - datetime.strptime(last_date, "%Y-%m-%d")).days
    if days_ago == 0:
        ago_str = "today"
    elif days_ago == 1:
        ago_str = "yesterday"
    else:
        ago_str = f"{days_ago} days ago"
    print(f"\nLast run:          {last_date} ({ago_str})")

    # Last result
    last_result = get_last_result()
    if last_result:
        print(f"Last result:       {last_result}")

    # Consecutive days (counting back from most recent run)
    consecutive = 0
    check_date = datetime.strptime(last_date, "%Y-%m-%d")
    while check_date.strftime("%Y-%m-%d") in run_dates:
        consecutive += 1
        check_date -= timedelta(days=1)
    print(f"Consecutive days:  {consecutive}")

    # Missed days in the last 7 completed days.
    # Today is deliberately excluded: the daily run may simply not have
    # happened yet (e.g. the scheduled GitHub Actions run doesn't fire
    # until later today), so flagging today before it's over would be a
    # false alarm rather than an actual missed day. Only days that have
    # fully elapsed (yesterday through 7 days ago) count toward misses.
    missed = []
    for i in range(1, 8):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        if d not in run_dates:
            missed.append(d)

    if missed:
        print(f"Missed (last 7d):  {len(missed)} — {', '.join(missed)}")
    else:
        print(f"Missed (last 7d):  None — perfect streak!")

    # Total runs
    print(f"Total runs:        {len(run_dates)}")
    print()


if __name__ == "__main__":
    check_status()
