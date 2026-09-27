# test_main_trades_flagged.py — Tests for main.py's trades_flagged count.
#
# Focus: trades_flagged used to hardcode `score > 25` instead of reading
# config.SCORE_NOTEWORTHY (the actual threshold scorer.tag_from_score() uses
# to decide what appears in the email). Customizing SCORE_NOTEWORTHY — which
# the README explicitly invites users to do — used to silently desync the
# run-log "flagged" count from what the email body actually shows.

import main as main_module


def _patch_pipeline(monkeypatch, scored_trades):
    monkeypatch.setattr(main_module, "get_new_trades", lambda: [{"filing_id": "house_1"}])
    monkeypatch.setattr(main_module, "get_new_senate_trades", lambda: [])
    monkeypatch.setattr(main_module, "parse_all_filings", lambda filings: [{"filing_id": "house_1"}])
    monkeypatch.setattr(main_module, "enrich_trades", lambda: None)
    monkeypatch.setattr(main_module, "score_trades", lambda: scored_trades)

    sent = {}

    def fake_send_report(scored, total_filings=None, **kwargs):
        sent["scored"] = scored
        sent["total_filings"] = total_filings
        return True

    monkeypatch.setattr(main_module, "send_report", fake_send_report)
    return sent


def _run_and_capture_log(monkeypatch, tmp_path):
    log_file = tmp_path / "run_log.txt"
    monkeypatch.setattr(main_module, "RUN_LOG_FILE", str(log_file))
    monkeypatch.setattr(main_module, "DATA_DIR", str(tmp_path))
    main_module.run()
    return log_file.read_text()


def test_trades_flagged_uses_default_noteworthy_threshold(monkeypatch, tmp_path):
    scored = [{"score": 10}, {"score": 26}, {"score": 30}]
    _patch_pipeline(monkeypatch, scored)
    log_text = _run_and_capture_log(monkeypatch, tmp_path)
    assert "2 flagged" in log_text


def test_trades_flagged_follows_customized_score_noteworthy(monkeypatch, tmp_path):
    """If a user raises SCORE_NOTEWORTHY in config.py (as the README invites
    them to), the run-log flagged count must move with it instead of
    staying pinned to the old hardcoded 25 cutoff."""
    monkeypatch.setattr(main_module, "SCORE_NOTEWORTHY", 40)
    scored = [{"score": 30}, {"score": 40}, {"score": 45}]
    _patch_pipeline(monkeypatch, scored)
    log_text = _run_and_capture_log(monkeypatch, tmp_path)
    # Only the two trades >= the customized 40 threshold should count as
    # flagged — the hardcoded-25 bug would have counted all three.
    assert "2 flagged" in log_text
