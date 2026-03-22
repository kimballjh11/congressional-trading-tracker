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
    """Read the run log and find the date of the last pipeline run."""
    if not os.path.exists(RUN_LOG_FILE):
        return None

    with open(RUN_LOG_FILE, "r") as f:
        lines = f.readlines()

    # Look for the most recent "Pipeline started" entry
    for line in reversed(lines):
        match = re.match(r"\[(\d{4}-\d{2}-\d{2})", line)
        if match and "Pipeline started" in line:
            return match.group(1)

    return None


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
