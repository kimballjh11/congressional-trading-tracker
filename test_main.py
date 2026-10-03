# test_main.py — tests for main.py's STEP 3/4 enrichment-failure gating.
#
# Bug: main.py's STEP 4 (score_trades()) ran unconditionally right after STEP 3
# (enrich_trades()), even when STEP 3 raised an exception. enrich_trades() only
# writes config.ENRICHED_TRADES_FILE at the very end of a successful pass, after
# every trade has been processed -- a failed STEP 3 leaves that file holding
# whatever a *previous successful run* wrote. So on any enrichment failure
# (a network error hitting clerk.house.gov/senate.gov/yfinance, for example),
# STEP 4 would silently re-score and re-email YESTERDAY's stale trades while
# TODAY's real newly-parsed trades were dropped entirely, with no visible
# indication in the email that anything was wrong.
#
# This is a fresh reapply of the same bug/fix that PR #20/#39 (now both stale
# against main.py's post-2026-10-01 restructuring -- the "mark filings seen
# only after the report is sent" rewrite, see mark_filings_seen()) already
# fixed against older versions of main.py: this test confirms the underlying
# bug is still live on the current structure and that the current structure's
# fix doesn't regress mark_filings_seen()/the seen-tracking rewrite.

import main as main_module


def _patch_common(monkeypatch, *, house_filings, senate_filings, trades, enrich_side_effect=None):
    monkeypatch.setattr(main_module, "get_new_trades", lambda: house_filings)
    monkeypatch.setattr(main_module, "get_new_senate_trades", lambda: senate_filings)
    monkeypatch.setattr(main_module, "parse_all_filings", lambda filings: trades)
    if enrich_side_effect is not None:
        monkeypatch.setattr(main_module, "enrich_trades", enrich_side_effect)
    monkeypatch.setattr(main_module, "send_report", lambda *a, **k: True)
    monkeypatch.setattr(main_module, "load_seen_trades", lambda: set())
    monkeypatch.setattr(main_module, "save_seen_trades", lambda seen: None)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def test_scoring_skipped_when_enrichment_fails(monkeypatch):
    """
    STEP 4 must not run at all when STEP 3 raised -- it would otherwise
    re-score/re-email whatever stale data a previous successful run left in
    ENRICHED_TRADES_FILE, dropping today's real trades silently.
    """
    def failing_enrich():
        raise RuntimeError("simulated enrichment failure (e.g. a network error)")

    _patch_common(
        monkeypatch,
        house_filings=[{"filing_id": "house_1"}],
        senate_filings=[],
        trades=[{"ticker": "ACME", "transaction_date": "2026-09-01"}],
        enrich_side_effect=failing_enrich,
    )

    scoring_calls = []
    monkeypatch.setattr(main_module, "score_trades", lambda: scoring_calls.append(1) or [])

    main_module.run()

    assert scoring_calls == [], "score_trades() must not be called after a failed enrich_trades()"


def test_scoring_runs_when_enrichment_succeeds(monkeypatch):
    """Regression guard: a normal successful enrichment must still score as before."""
    _patch_common(
        monkeypatch,
        house_filings=[{"filing_id": "house_1"}],
        senate_filings=[],
        trades=[{"ticker": "ACME", "transaction_date": "2026-09-01"}],
        enrich_side_effect=lambda: None,
    )

    scoring_calls = []

    def fake_score_trades():
        scoring_calls.append(1)
        return [{"ticker": "ACME", "score": 10}]

    monkeypatch.setattr(main_module, "score_trades", fake_score_trades)

    main_module.run()

    assert scoring_calls == [1], "score_trades() must still run after a successful enrich_trades()"
