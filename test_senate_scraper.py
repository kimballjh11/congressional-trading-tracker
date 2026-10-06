# test_senate_scraper.py — Tests for the Senate scan-cursor / extended-lookback logic
#
# The Senate EFDS search backend has intermittent extended outages (as of
# this writing, ~75+ days straight at one point). Without a persisted scan
# cursor, the scraper's fixed 45-day lookback window means any PTR filing
# submitted more than 45 days before the backend recovers is silently and
# permanently missed, even though get_new_senate_trades() raises on failure
# (so main.py's error_occurred tracking still sees the outage).

import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import senate_scraper
from config import SENATE_DEFAULT_LOOKBACK_DAYS, SENATE_MAX_LOOKBACK_DAYS, SENATE_SCAN_OVERLAP_DAYS


@pytest.fixture
def cursor_file(tmp_path, monkeypatch):
    path = str(tmp_path / "senate_scan_cursor.json")
    monkeypatch.setattr(senate_scraper, "SENATE_SCAN_CURSOR_FILE", path)
    monkeypatch.setattr(senate_scraper, "DATA_DIR", str(tmp_path))
    return path


def test_compute_search_start_date_no_cursor_uses_default_lookback(cursor_file):
    now = datetime(2026, 10, 6)
    start = senate_scraper.compute_search_start_date(now)
    assert start == now - timedelta(days=SENATE_DEFAULT_LOOKBACK_DAYS)


def test_compute_search_start_date_recent_cursor_still_uses_default_window(cursor_file):
    now = datetime(2026, 10, 6)
    # A cursor from 5 days ago is well within the 45-day default window, so
    # the default window (further back) should still win.
    senate_scraper.save_last_scan_date(now - timedelta(days=5))
    start = senate_scraper.compute_search_start_date(now)
    assert start == now - timedelta(days=SENATE_DEFAULT_LOOKBACK_DAYS)


def test_compute_search_start_date_stale_cursor_extends_window(cursor_file):
    now = datetime(2026, 10, 6)
    # A cursor from 90 days ago (e.g. after a long EFDS outage) is older
    # than the default 45-day window, so the window must extend back to
    # cover the gap (minus the overlap buffer), not silently drop filings
    # submitted 46-90 days ago.
    senate_scraper.save_last_scan_date(now - timedelta(days=90))
    start = senate_scraper.compute_search_start_date(now)
    assert start == now - timedelta(days=90 + SENATE_SCAN_OVERLAP_DAYS)


def test_compute_search_start_date_caps_at_max_lookback(cursor_file):
    now = datetime(2026, 10, 6)
    # Even a very stale/ancient cursor can't push the window further back
    # than SENATE_MAX_LOOKBACK_DAYS, so a corrupt cursor can't trigger an
    # effectively-unbounded scan.
    senate_scraper.save_last_scan_date(now - timedelta(days=5000))
    start = senate_scraper.compute_search_start_date(now)
    assert start == now - timedelta(days=SENATE_MAX_LOOKBACK_DAYS)


def test_compute_search_start_date_corrupt_cursor_falls_back_to_default(cursor_file, capsys):
    now = datetime(2026, 10, 6)
    os.makedirs(os.path.dirname(cursor_file), exist_ok=True)
    with open(cursor_file, "w") as f:
        f.write("not valid json {{{")

    start = senate_scraper.compute_search_start_date(now)
    assert start == now - timedelta(days=SENATE_DEFAULT_LOOKBACK_DAYS)


def test_save_and_load_last_scan_date_round_trip(cursor_file):
    date = datetime(2026, 9, 1)
    senate_scraper.save_last_scan_date(date)
    loaded = senate_scraper.load_last_scan_date()
    assert loaded == date


def test_load_last_scan_date_missing_file_returns_none(cursor_file):
    assert senate_scraper.load_last_scan_date() is None


def test_get_new_senate_trades_advances_cursor_on_success(cursor_file):
    """A successful search should advance the scan cursor to 'now'."""
    with patch.object(senate_scraper, "load_seen_trades", return_value=set()), \
         patch.object(senate_scraper, "create_session", return_value=object()), \
         patch.object(senate_scraper, "search_ptr_filings", return_value=[]):
        senate_scraper.get_new_senate_trades()

    assert senate_scraper.load_last_scan_date() is not None


def test_get_new_senate_trades_does_not_advance_cursor_on_failure(cursor_file):
    """
    If the search raises (bad status, maintenance page, bad JSON — all of
    which search_ptr_filings signals by raising), the cursor must NOT
    advance, so the next run retries the same (or wider) window instead of
    silently narrowing it. The exception must also still propagate so
    main.py's existing try/except continues to flag error_occurred=True.
    """
    with patch.object(senate_scraper, "load_seen_trades", return_value=set()), \
         patch.object(senate_scraper, "create_session", return_value=object()), \
         patch.object(
             senate_scraper,
             "search_ptr_filings",
             side_effect=RuntimeError("Senate EFDS search backend is under maintenance"),
         ):
        with pytest.raises(RuntimeError):
            senate_scraper.get_new_senate_trades()

    assert senate_scraper.load_last_scan_date() is None


def test_get_new_senate_trades_uses_computed_start_and_end_date(cursor_file):
    """The computed window should actually be passed through to the search call."""
    captured = {}

    def fake_search(session, start_date=None, end_date=None):
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        return []

    old_cursor = datetime.now() - timedelta(days=90)
    senate_scraper.save_last_scan_date(old_cursor)

    with patch.object(senate_scraper, "load_seen_trades", return_value=set()), \
         patch.object(senate_scraper, "create_session", return_value=object()), \
         patch.object(senate_scraper, "search_ptr_filings", side_effect=fake_search):
        senate_scraper.get_new_senate_trades()

    expected_start = old_cursor - timedelta(days=SENATE_SCAN_OVERLAP_DAYS)
    assert captured["start_date"] == expected_start.strftime("%m/%d/%Y")
    assert captured["end_date"] == datetime.now().strftime("%m/%d/%Y")
