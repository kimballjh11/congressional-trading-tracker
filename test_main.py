# test_main.py — Regression tests for main.py's pipeline step-gating.
#
# Covers a real, live-reproduced bug: STEP 4 (score_trades) used to run
# unconditionally right after STEP 3 (enrich_trades), even when STEP 3
# raised an exception. enrich_trades() only writes ENRICHED_TRADES_FILE at
# the very end of a successful pass, so a failed STEP 3 leaves that file
# holding whatever a *previous* successful run wrote. Scoring it anyway
# silently re-flags/re-emails stale, already-reported trades while the
# newly parsed trades from the failed run are dropped entirely.

import json
from unittest.mock import patch

import pytest

import main as main_module


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Point main.py's file-path constants at a scratch directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    run_log = data_dir / "run_log.txt"

    monkeypatch.setattr(main_module, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main_module, "RUN_LOG_FILE", str(run_log))

    return {"data_dir": data_dir, "run_log": run_log}


def _one_filing():
    return [{"filing_id": "house_12345678", "representative": "Test Member"}]


def test_scoring_skipped_when_enrichment_raises(isolated_paths, monkeypatch):
    """STEP 4 must NOT run at all when STEP 3 raises."""
    monkeypatch.setattr(main_module, "get_new_trades", lambda: _one_filing())
    monkeypatch.setattr(main_module, "get_new_senate_trades", lambda: [])
    monkeypatch.setattr(main_module, "parse_all_filings", lambda filings: [{"asset": "X"}])
    monkeypatch.setattr(
        main_module, "enrich_trades",
        lambda: (_ for _ in ()).throw(RuntimeError("simulated enrichment failure")),
    )
    monkeypatch.setattr(main_module, "send_report", lambda scored, **kwargs: True)

    with patch.object(main_module, "score_trades") as mock_score:
        main_module.run()
        mock_score.assert_not_called()


def test_scoring_runs_when_enrichment_succeeds(isolated_paths, monkeypatch):
    """Regression guard: normal successful runs must still score as before."""
    monkeypatch.setattr(main_module, "get_new_trades", lambda: _one_filing())
    monkeypatch.setattr(main_module, "get_new_senate_trades", lambda: [])
    monkeypatch.setattr(main_module, "parse_all_filings", lambda filings: [{"asset": "X"}])
    monkeypatch.setattr(main_module, "enrich_trades", lambda: None)
    monkeypatch.setattr(main_module, "send_report", lambda scored, **kwargs: True)

    with patch.object(main_module, "score_trades", return_value=[{"asset": "X", "score": 0}]) as mock_score:
        main_module.run()
        mock_score.assert_called_once()


def test_stale_enriched_data_not_rescored_end_to_end(isolated_paths, monkeypatch):
    """
    Full pipeline reproduction: seed ENRICHED_TRADES_FILE with a stale
    trade from a "previous successful run", make enrich_trades() fail
    for "today's" run, and confirm the stale trade is never re-scored or
    re-emailed, and that today's freshly parsed trade is not silently
    substituted in either — scoring is skipped outright.
    """
    import scorer as scorer_module

    scored_file = isolated_paths["data_dir"] / "scored_trades.json"
    enriched_file = isolated_paths["data_dir"] / "enriched_trades.json"

    monkeypatch.setattr(scorer_module, "ENRICHED_TRADES_FILE", str(enriched_file))
    monkeypatch.setattr(scorer_module, "SCORED_TRADES_FILE", str(scored_file))
    monkeypatch.setattr(scorer_module, "DATA_DIR", str(isolated_paths["data_dir"]))

    stale_trade = {"representative": "OLD MEMBER, Yesterday", "asset": "OldCorp", "score": 0}
    enriched_file.write_text(json.dumps([stale_trade]))

    monkeypatch.setattr(main_module, "get_new_trades", lambda: _one_filing())
    monkeypatch.setattr(main_module, "get_new_senate_trades", lambda: [])
    monkeypatch.setattr(
        main_module, "parse_all_filings",
        lambda filings: [{"representative": "NEW MEMBER, Today", "asset": "NewCorp"}],
    )
    monkeypatch.setattr(
        main_module, "enrich_trades",
        lambda: (_ for _ in ()).throw(RuntimeError("simulated network failure mid-enrichment")),
    )

    sent = {}
    def fake_send_report(scored, **kwargs):
        sent["scored"] = scored
        return True
    monkeypatch.setattr(main_module, "send_report", fake_send_report)

    main_module.run()

    # Scoring was skipped entirely, so the stale enriched file on disk is
    # untouched and the report sent for today reflects that (empty), not
    # a re-flagging of yesterday's stale trade.
    assert enriched_file.read_text() == json.dumps([stale_trade])
    assert sent["scored"] == []
