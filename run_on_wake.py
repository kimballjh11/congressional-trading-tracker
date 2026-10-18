# run_on_wake.py — Run the trading pipeline once per day on wake/login
# Checks the run log to see if we've already run today.
# Usage:
#   python run_on_wake.py          # Normal mode: skip if already ran today
#   python run_on_wake.py --test   # Force a run regardless of last run date

import sys
import os
import re
from datetime import datetime

# Ensure we're running from the project directory
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

from config import RUN_LOG_FILE


def get_last_run_date():
    """Read the run log and find the date of the last pipeline run that
    actually ran to completion (logged a SUCCESS or PARTIAL result).

    A run that only logged "Pipeline started" — because the process was
    killed, the machine slept/lost power, or an unhandled crash occurred —
    does NOT count. Otherwise a crashed run with no email ever sent would
    still block every retry (cron or manual) for the rest of the day.
    """
    if not os.path.exists(RUN_LOG_FILE):
        return None

    with open(RUN_LOG_FILE, "r") as f:
        lines = f.readlines()

    pending_start_date = None
    last_completed_date = None
    for line in lines:
        match = re.match(r"\[(\d{4}-\d{2}-\d{2})", line)
        if not match:
            continue
        if "Pipeline started" in line:
            pending_start_date = match.group(1)
        elif pending_start_date and re.search(r"Pipeline (SUCCESS|PARTIAL)\b", line):
            last_completed_date = pending_start_date
            pending_start_date = None

    return last_completed_date


def already_ran_today():
    """Check if the pipeline has already run today."""
    last_date = get_last_run_date()
    if not last_date:
        return False
    today = datetime.now().strftime("%Y-%m-%d")
    return last_date == today


def main():
    force = "--test" in sys.argv

    if not force and already_ran_today():
        print("Pipeline already ran today. Skipping.")
        return

    if force:
        print("--test flag: forcing pipeline run")

    # Import and run the pipeline
    from main import run
    run()


if __name__ == "__main__":
    main()
