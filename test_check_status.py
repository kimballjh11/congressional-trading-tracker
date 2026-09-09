# test_check_status.py — Tests for check_status.py's "missed days" health check
#
# Bug: the "Missed (last 7d)" check in check_status() built its date window
# with `range(7)`, i.e. today (i=0) through 6 days ago. That means TODAY is
# always included in the missed-day check — even though the daily pipeline
# may simply not have run *yet* (its GitHub Actions schedule can fire any
# time from the morning into the evening UTC, see daily-report.yml). Anyone
# running `check_status.py` earlier in the day than the workflow's actual
# fire time would see today listed as "missed" even on a perfect run streak,
# a false alarm rather than a real gap. No other open PR touches this file.
#
# Fix: only count days that have fully elapsed — yesterday (i=1) through 7
# days ago (i=7) — toward "missed", excluding today entirely.

import io
import os
from contextlib import redirect_stdout
from datetime import datetime, timedelta

import config
import check_status


def _write_run_log(tmp_path, dates):
    """Write a run_log.txt with a 'Pipeline started'/'SUCCESS' pair for each
    date string in `dates`, in chronological (append) order — matching how
    main.py's log() function actually writes the real file."""
    log_path = tmp_path / "run_log.txt"
    lines = []
    for d in dates:
        lines.append(f"[{d} 13:05:00] Pipeline started\n")
        lines.append(f"[{d} 13:05:30] Pipeline SUCCESS — 0 new filings, email sent\n")
    log_path.write_text("".join(lines))
    return str(log_path)


def _days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _run_check_status(monkeypatch, log_path):
    monkeypatch.setattr(config, "RUN_LOG_FILE", log_path)
    monkeypatch.setattr(check_status, "RUN_LOG_FILE", log_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        check_status.check_status()
    return buf.getvalue()


def test_today_not_yet_run_is_not_reported_as_missed(tmp_path, monkeypatch):
    """A perfect streak through yesterday, with today's run simply not
    having happened yet, must NOT be reported as a missed day."""
    dates = [_days_ago(i) for i in range(1, 8)]  # yesterday .. 7 days ago
    log_path = _write_run_log(tmp_path, dates)

    output = _run_check_status(monkeypatch, log_path)

    assert _days_ago(0) not in output
    assert "perfect streak" in output.lower()


def test_a_real_gap_in_the_last_7_days_is_still_reported(tmp_path, monkeypatch):
    """A genuine missed day (not today) must still show up."""
    all_days_except_3_ago = [_days_ago(i) for i in range(1, 8) if i != 3]
    log_path = _write_run_log(tmp_path, all_days_except_3_ago)

    output = _run_check_status(monkeypatch, log_path)

    assert _days_ago(3) in output
    assert _days_ago(0) not in output


def test_missed_window_covers_exactly_the_last_7_completed_days(tmp_path, monkeypatch):
    """8-days-ago is outside the window and must not be reported even if
    missing; 7-days-ago is the oldest day inside the window."""
    dates = [_days_ago(i) for i in range(1, 7)]  # yesterday .. 6 days ago
    log_path = _write_run_log(tmp_path, dates)

    output = _run_check_status(monkeypatch, log_path)

    assert _days_ago(7) in output
    assert _days_ago(8) not in output


def test_no_runs_at_all_still_handled_gracefully(tmp_path, monkeypatch):
    """Sanity check unrelated to the fix: an empty/missing log shouldn't
    crash and shouldn't claim a perfect streak."""
    log_path = str(tmp_path / "run_log.txt")  # never created

    output = _run_check_status(monkeypatch, log_path)

    assert "No runs recorded yet" in output
