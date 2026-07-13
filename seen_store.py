# seen_store.py — Shared persistence for filing IDs the pipeline has processed.
#
# IMPORTANT: a filing_id should only be added here once it has been
# successfully parsed (or otherwise confirmed as "nothing more to do").
# Marking a filing as seen before it's actually parsed means a transient
# failure (network blip, download error, etc.) permanently loses that
# filing — it will never be scraped or retried again. See main.py /
# parser.py for how the "successful parse" confirmation flows back here.

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
    Call this only for filings that were actually successfully processed
    (e.g. confirmed parsed) — never merely "fetched" or "queued".
    """
    if not filing_ids:
        return

    seen = load_seen_trades()
    seen.update(filing_ids)
    save_seen_trades(seen)
