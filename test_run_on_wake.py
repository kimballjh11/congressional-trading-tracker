# test_run_on_wake.py — tests for run_on_wake.py's once-per-day skip logic
#
# Covers a real bug: get_last_run_date()/already_ran_today() used to treat any
# "Pipeline started" log line as a completed run, even if the pipeline crashed
# before ever logging a SUCCESS/PARTIAL result. That meant a crashed run (dead
# process, machine sleep/power loss, uncaught exception) silently blocked every
# retry -- cron or manual -- for the rest of the day, with no email ever sent.

from datetime import datetime, timedelta

import run_on_wake

TODAY = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def write_log(path, lines):
    with open(path, "w") as f:
        for line in lines:
            f.write(line + "\n")


def test_crashed_run_is_not_treated_as_completed(tmp_path, monkeypatch):
    """A run that only logged 'Pipeline started' (crashed before finishing)
    must not count as a completed run for today."""
    log_file = tmp_path / "run_log.txt"
    write_log(log_file, [f"[{TODAY} 08:00:00] Pipeline started"])
    monkeypatch.setattr(run_on_wake, "RUN_LOG_FILE", str(log_file))

    assert run_on_wake.get_last_run_date() is None
    assert run_on_wake.already_ran_today() is False


def test_successful_run_today_is_skipped(tmp_path, monkeypatch):
    """A normal SUCCESS-completed run today should still be treated as
    already having run (regression guard for the normal path)."""
    log_file = tmp_path / "run_log.txt"
    write_log(
        log_file,
        [
            f"[{TODAY} 08:00:00] Pipeline started",
            f"[{TODAY} 08:00:05] Pipeline SUCCESS — 0 new filings, email sent",
        ],
    )
    monkeypatch.setattr(run_on_wake, "RUN_LOG_FILE", str(log_file))

    assert run_on_wake.get_last_run_date() == TODAY
    assert run_on_wake.already_ran_today() is True


def test_partial_run_today_is_skipped(tmp_path, monkeypatch):
    """PARTIAL (a step failed but an email was still sent) is a completed
    run too and should not force a retry."""
    log_file = tmp_path / "run_log.txt"
    write_log(
        log_file,
        [
            f"[{TODAY} 08:00:00] Pipeline started",
            f"[{TODAY} 08:00:05] Pipeline PARTIAL — 3 filings, 1 trades parsed, 0 flagged, email sent",
        ],
    )
    monkeypatch.setattr(run_on_wake, "RUN_LOG_FILE", str(log_file))

    assert run_on_wake.already_ran_today() is True


def test_todays_crash_falls_back_to_yesterdays_completed_run(tmp_path, monkeypatch):
    """If yesterday completed successfully but today's run crashed partway
    through, get_last_run_date() should report yesterday (not today), and
    already_ran_today() should allow a retry today."""
    log_file = tmp_path / "run_log.txt"
    write_log(
        log_file,
        [
            f"[{YESTERDAY} 08:00:00] Pipeline started",
            f"[{YESTERDAY} 08:00:05] Pipeline SUCCESS — 5 filings, 2 trades parsed, 0 flagged, email sent",
            f"[{TODAY} 08:00:00] Pipeline started",
        ],
    )
    monkeypatch.setattr(run_on_wake, "RUN_LOG_FILE", str(log_file))

    assert run_on_wake.get_last_run_date() == YESTERDAY
    assert run_on_wake.already_ran_today() is False


def test_retry_after_crash_then_completes_is_recognized(tmp_path, monkeypatch):
    """A crashed attempt earlier today followed by a successful --test retry
    later today should be recognized as completed."""
    log_file = tmp_path / "run_log.txt"
    write_log(
        log_file,
        [
            f"[{TODAY} 08:00:00] Pipeline started",  # crashed, no completion line
            f"[{TODAY} 09:00:00] Pipeline started",  # retry
            f"[{TODAY} 09:00:05] Pipeline SUCCESS — 0 new filings, email sent",
        ],
    )
    monkeypatch.setattr(run_on_wake, "RUN_LOG_FILE", str(log_file))

    assert run_on_wake.get_last_run_date() == TODAY
    assert run_on_wake.already_ran_today() is True


def test_no_log_file_means_never_ran(tmp_path, monkeypatch):
    log_file = tmp_path / "does_not_exist.txt"
    monkeypatch.setattr(run_on_wake, "RUN_LOG_FILE", str(log_file))

    assert run_on_wake.get_last_run_date() is None
    assert run_on_wake.already_ran_today() is False
