"""Tests for main.py's run() pipeline orchestration.

Focus: the "N flagged" count written to the run log must track whichever
threshold scorer.py actually uses to tag a trade "noteworthy" (i.e.
config.SCORE_NOTEWORTHY), not a hardcoded literal — otherwise the log
can silently disagree with what the email reports if SCORE_NOTEWORTHY is
ever customized (which config.py's own comments and the README invite
users to do).
"""

from unittest.mock import patch

import main


def _run_with_mocks(monkeypatch, tmp_path, scored_trades, score_noteworthy):
    run_log = tmp_path / "run_log.txt"
    monkeypatch.setattr(main, "RUN_LOG_FILE", str(run_log))
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "SCORE_NOTEWORTHY", score_noteworthy)
    monkeypatch.setattr(main, "mark_filings_seen", lambda filings: None)

    fake_filing = {"filing_id": "house_1"}

    with patch("main.get_new_trades", return_value=[fake_filing]), \
         patch("main.get_new_senate_trades", return_value=[]), \
         patch("main.parse_all_filings", return_value=[{"filing_id": "house_1"}]), \
         patch("main.enrich_trades"), \
         patch("main.score_trades", return_value=scored_trades), \
         patch("main.send_report", return_value=True):
        main.run()

    return run_log.read_text()


def test_flagged_count_uses_config_noteworthy_threshold_when_customized(monkeypatch, tmp_path):
    """With SCORE_NOTEWORTHY customized to 30, a trade scoring 28 must NOT
    be counted as flagged, even though a hardcoded '> 25' check would
    wrongly include it."""
    scored = [{"score": 28}, {"score": 35}, {"score": 10}]
    log_text = _run_with_mocks(monkeypatch, tmp_path, scored, score_noteworthy=30)

    assert "1 flagged" in log_text, log_text


def test_flagged_count_matches_default_noteworthy_threshold(monkeypatch, tmp_path):
    scored = [{"score": 26}, {"score": 25}, {"score": 50}]
    log_text = _run_with_mocks(monkeypatch, tmp_path, scored, score_noteworthy=26)

    assert "2 flagged" in log_text, log_text
