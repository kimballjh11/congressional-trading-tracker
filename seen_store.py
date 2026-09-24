# seen_store.py — Shared persistence for filing IDs the pipeline has processed.
#
# IMPORTANT: a filing_id should only be added here once it has actually been
# fetched and parsed successfully (see parser.parse_all_filings / main.run).
# Marking a filing as "seen" any earlier than that — e.g. the moment it's
# merely discovered in a search-results listing — means a transient failure
# (network blip, a bad HTTP status, an empty response, etc.) permanently
# loses that filing: it will never be retried again and its trades never
# appear in a report.

import json
import os

from config import SEEN_TRADES_FILE, DATA_DIR


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
    Overwrite the seen-filings file with the given set of filing IDs.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEEN_TRADES_FILE, "w") as f:
        json.dump(list(seen), f)


def mark_seen(filing_ids):
    """
    Add the given filing IDs to the persisted seen set.

    Call this ONLY for filings that were actually fetched and parsed
    successfully — never merely "found in a listing" or "queued". A filing
    that failed to download/parse should be left out so it's picked up
    again (and retried) on the next run instead of being silently lost.
    """
    if not filing_ids:
        return

    seen = load_seen_trades()
    seen.update(filing_ids)
    save_seen_trades(seen)
