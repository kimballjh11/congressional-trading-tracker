# test_main_error_visibility.py — end-to-end regression test that a failed
# pipeline step actually reaches the emailed report, not just the run log.
#
# See test_emailer.py for the detailed bug writeup. This test exercises the
# real main.run() orchestration (not just emailer.py's functions in
# isolation) to confirm main.py actually collects and forwards step
# failures into send_report()'s `errors` argument.

import pytest

import main as main_module


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    run_log = data_dir / "run_log.txt"
    monkeypatch.setattr(main_module, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main_module, "RUN_LOG_FILE", str(run_log))
    return {"data_dir": data_dir, "run_log": run_log}


def test_both_scrapers_failing_reaches_email_as_errors(isolated_paths, monkeypatch):
    """Reproduces the original bug: both scrapers raising must not look like a quiet day."""
    monkeypatch.setattr(
        main_module, "get_new_trades",
        lambda: (_ for _ in ()).throw(RuntimeError("House Clerk site down (503)")),
    )
    monkeypatch.setattr(
        main_module, "get_new_senate_trades",
        lambda: (_ for _ in ()).throw(RuntimeError("Senate EFDS site down (503)")),
    )

    captured = {}

    def fake_send_report(scored_trades, total_filings=None, no_new_filings=False, errors=None):
        captured["no_new_filings"] = no_new_filings
        captured["errors"] = errors
        return True

    monkeypatch.setattr(main_module, "send_report", fake_send_report)

    main_module.run()

    assert captured["no_new_filings"] is True
    assert captured["errors"] is not None
    assert len(captured["errors"]) == 2
    assert any("House scraper" in e for e in captured["errors"])
    assert any("Senate scraper" in e for e in captured["errors"])


def test_parser_crash_reaches_email_as_errors(isolated_paths, monkeypatch):
    """Reproduces the original bug: a parser crash must not look like '0 routine trades'."""
    monkeypatch.setattr(
        main_module, "get_new_trades",
        lambda: [{"filing_id": "house_1", "representative": "Doe, Jane"}],
    )
    monkeypatch.setattr(main_module, "get_new_senate_trades", lambda: [])
    monkeypatch.setattr(
        main_module, "parse_all_filings",
        lambda filings: (_ for _ in ()).throw(RuntimeError("pdfplumber crashed")),
    )

    captured = {}

    def fake_send_report(scored_trades, total_filings=None, no_new_filings=False, errors=None):
        captured["scored_trades"] = scored_trades
        captured["errors"] = errors
        return True

    monkeypatch.setattr(main_module, "send_report", fake_send_report)

    main_module.run()

    assert captured["scored_trades"] == []
    assert captured["errors"] is not None
    assert any("Parser failed" in e for e in captured["errors"])


def test_clean_run_has_no_errors_regression(isolated_paths, monkeypatch):
    """Regression guard: a fully successful run still passes an empty errors list."""
    monkeypatch.setattr(main_module, "get_new_trades", lambda: [])
    monkeypatch.setattr(main_module, "get_new_senate_trades", lambda: [])

    captured = {}

    def fake_send_report(scored_trades, total_filings=None, no_new_filings=False, errors=None):
        captured["errors"] = errors
        return True

    monkeypatch.setattr(main_module, "send_report", fake_send_report)

    main_module.run()

    assert captured["errors"] == []
