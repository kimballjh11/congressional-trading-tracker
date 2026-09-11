# test_check_status.py — tests for check_status.py's run-date parsing
#
# Covers a real bug: parse_run_dates() used to treat any "Pipeline started"
# log line as a completed run day, even if the pipeline crashed before ever
# logging a SUCCESS/PARTIAL result. That meant a day where the process was
# killed, the machine slept/lost power, or an unhandled crash occurred would
# still count toward "Consecutive days" and never show up in "Missed (last
# 7d)" -- silently hiding the exact kind of failure this health check exists
# to catch. Orthogonal to PR #35 (which only fixed the separate "today is
# always in the missed-days window" bug and never touched parse_run_dates()).

from datetime import datetime, timedelta

import check_status

TODAY = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
TWO_DAYS_AGO = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")


def write_log(path, lines):
    with open(path, "w") as f:
        for line in lines:
            f.write(line + "\n")


def test_crashed_run_is_not_counted(tmp_path, monkeypatch):
    """A run that only logged 'Pipeline started' (crashed before finishing)
    must not count as a completed run day."""
    log_file = tmp_path / "run_log.txt"
    write_log(log_file, [f"[{TODAY} 08:00:00] Pipeline started"])
    monkeypatch.setattr(check_status, "RUN_LOG_FILE", str(log_file))

    assert check_status.parse_run_dates() == []


def test_completed_success_run_is_counted(tmp_path, monkeypatch):
    """Regression guard: a normal SUCCESS-completed run should still count."""
    log_file = tmp_path / "run_log.txt"
    write_log(
        log_file,
        [
            f"[{TODAY} 08:00:00] Pipeline started",
            f"[{TODAY} 08:00:05] Pipeline SUCCESS — 0 new filings, email sent",
        ],
    )
    monkeypatch.setattr(check_status, "RUN_LOG_FILE", str(log_file))

    assert check_status.parse_run_dates() == [TODAY]


def test_completed_partial_run_is_counted(tmp_path, monkeypatch):
    """PARTIAL (a step failed but an email was still sent) is a completed
    run too and should count."""
    log_file = tmp_path / "run_log.txt"
    write_log(
        log_file,
        [
            f"[{TODAY} 08:00:00] Pipeline started",
            f"[{TODAY} 08:00:05] Pipeline PARTIAL — 3 filings, 1 trades parsed, 0 flagged, email sent",
        ],
    )
    monkeypatch.setattr(check_status, "RUN_LOG_FILE", str(log_file))

    assert check_status.parse_run_dates() == [TODAY]


def test_crashed_day_does_not_break_a_real_streak(tmp_path, monkeypatch):
    """A crashed run today, with yesterday and the day before completing
    normally, should report the real 2-day streak ending yesterday -- not a
    3-day streak that silently includes today's crash."""
    log_file = tmp_path / "run_log.txt"
    write_log(
        log_file,
        [
            f"[{TWO_DAYS_AGO} 08:00:00] Pipeline started",
            f"[{TWO_DAYS_AGO} 08:00:05] Pipeline SUCCESS — 5 filings, 2 trades parsed, 0 flagged, email sent",
            f"[{YESTERDAY} 08:00:00] Pipeline started",
            f"[{YESTERDAY} 08:00:05] Pipeline SUCCESS — 7 filings, 3 trades parsed, 1 flagged, email sent",
            f"[{TODAY} 08:00:00] Pipeline started",  # crashed, no completion line
        ],
    )
    monkeypatch.setattr(check_status, "RUN_LOG_FILE", str(log_file))

    dates = check_status.parse_run_dates()
    assert dates == [TWO_DAYS_AGO, YESTERDAY]
    assert TODAY not in dates


def test_retry_after_crash_then_completes_is_recognized(tmp_path, monkeypatch):
    """A crashed attempt earlier today followed by a successful --test retry
    later today should still count today as a completed run day."""
    log_file = tmp_path / "run_log.txt"
    write_log(
        log_file,
        [
            f"[{TODAY} 08:00:00] Pipeline started",  # crashed, no completion line
            f"[{TODAY} 09:00:00] Pipeline started",  # retry
            f"[{TODAY} 09:00:05] Pipeline SUCCESS — 0 new filings, email sent",
        ],
    )
    monkeypatch.setattr(check_status, "RUN_LOG_FILE", str(log_file))

    assert check_status.parse_run_dates() == [TODAY]


def test_no_log_file_means_no_run_dates(tmp_path, monkeypatch):
    log_file = tmp_path / "does_not_exist.txt"
    monkeypatch.setattr(check_status, "RUN_LOG_FILE", str(log_file))

    assert check_status.parse_run_dates() == []
