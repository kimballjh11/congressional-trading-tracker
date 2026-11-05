"""Tests for scorer.py's cross-run cluster-trading memory (score_cluster_trades).

Each pipeline run only scores the filings scraped that run. Real PTR filings
for trades around the same time routinely land on different days (disclosure
delays vary member to member), so without persisted cross-run history, two
members trading the same stock days or weeks apart would never be detected
as a cluster unless both filings happened to be scraped on the exact same
day. These tests verify score_cluster_trades() persists trade records to
CLUSTER_HISTORY_FILE and reuses them on later calls/runs.
"""

import json
import os
from datetime import datetime, timedelta

import scorer


def _trade(ticker, representative, filing_id, date):
    return {
        "ticker": ticker,
        "representative": representative,
        "filing_id": filing_id,
        "transaction_date": date,
    }


def _days_ago(n):
    """A date string n days before today, always inside the lookback window."""
    return (datetime.now() - timedelta(days=n)).strftime("%m/%d/%Y")


def test_single_run_two_members_still_detected(tmp_path, monkeypatch):
    """Baseline: two members in the SAME run's batch are still flagged."""
    monkeypatch.setattr(scorer, "CLUSTER_HISTORY_FILE", str(tmp_path / "cluster_history.json"))
    monkeypatch.setattr(scorer, "DATA_DIR", str(tmp_path))

    trades = [
        _trade("AAPL", "Alice", "house_1", _days_ago(5)),
        _trade("AAPL", "Bob", "house_2", _days_ago(4)),
    ]
    results = scorer.score_cluster_trades(trades)
    assert "AAPL" in results
    pts, members = results["AAPL"]
    assert pts == scorer.POINTS_CLUSTER_2
    assert set(members) == {"Alice", "Bob"}


def test_members_across_different_runs_are_clustered(tmp_path, monkeypatch):
    """The core bug: Member A's trade from a PAST run must still combine
    with Member B's trade from TODAY'S run to form a cluster."""
    monkeypatch.setattr(scorer, "CLUSTER_HISTORY_FILE", str(tmp_path / "cluster_history.json"))
    monkeypatch.setattr(scorer, "DATA_DIR", str(tmp_path))

    # Run 1: only Alice trades AAPL.
    run1 = [_trade("AAPL", "Alice", "house_1", _days_ago(60))]
    results1 = scorer.score_cluster_trades(run1)
    assert "AAPL" not in results1  # only 1 member so far

    # Run 2 (a later pipeline run, different filings batch): only Bob trades AAPL.
    run2 = [_trade("AAPL", "Bob", "house_2", _days_ago(10))]
    results2 = scorer.score_cluster_trades(run2)

    assert "AAPL" in results2, "cross-run cluster was not detected"
    pts, members = results2["AAPL"]
    assert pts == scorer.POINTS_CLUSTER_2
    assert set(members) == {"Alice", "Bob"}


def test_history_file_is_persisted_between_calls(tmp_path, monkeypatch):
    history_file = tmp_path / "cluster_history.json"
    monkeypatch.setattr(scorer, "CLUSTER_HISTORY_FILE", str(history_file))
    monkeypatch.setattr(scorer, "DATA_DIR", str(tmp_path))

    scorer.score_cluster_trades([_trade("MSFT", "Alice", "house_1", _days_ago(5))])

    assert history_file.exists()
    with open(history_file) as f:
        records = json.load(f)
    assert len(records) == 1
    assert records[0]["representative"] == "Alice"
    assert records[0]["ticker"] == "MSFT"


def test_rerunning_same_trades_does_not_duplicate_or_inflate_count(tmp_path, monkeypatch):
    """Re-processing the same filing (e.g. a retried run) must not make a
    single member look like a multi-member cluster."""
    monkeypatch.setattr(scorer, "CLUSTER_HISTORY_FILE", str(tmp_path / "cluster_history.json"))
    monkeypatch.setattr(scorer, "DATA_DIR", str(tmp_path))

    trade = _trade("TSLA", "Alice", "house_1", _days_ago(5))
    scorer.score_cluster_trades([trade])
    results = scorer.score_cluster_trades([trade])

    assert "TSLA" not in results  # still just 1 distinct member
    history = scorer.load_cluster_history()
    assert len(history) == 1  # deduped, not appended twice


def test_history_older_than_lookback_window_is_pruned(tmp_path, monkeypatch):
    """A trade far outside CLUSTER_LOOKBACK_DAYS must not still count toward
    a cluster — otherwise unrelated trades years apart would falsely match."""
    monkeypatch.setattr(scorer, "CLUSTER_HISTORY_FILE", str(tmp_path / "cluster_history.json"))
    monkeypatch.setattr(scorer, "DATA_DIR", str(tmp_path))

    old_date = _days_ago(400)  # far older than CLUSTER_LOOKBACK_DAYS
    scorer.save_cluster_history([{
        "filing_id": "house_old",
        "ticker": "GOOG",
        "representative": "Alice",
        "transaction_date": old_date,
    }])

    results = scorer.score_cluster_trades([_trade("GOOG", "Bob", "house_new", _days_ago(5))])
    assert "GOOG" not in results  # Alice's stale record should have been pruned

    history = scorer.load_cluster_history()
    assert all(r["representative"] != "Alice" for r in history)


def test_three_plus_members_across_runs_gets_higher_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(scorer, "CLUSTER_HISTORY_FILE", str(tmp_path / "cluster_history.json"))
    monkeypatch.setattr(scorer, "DATA_DIR", str(tmp_path))

    scorer.score_cluster_trades([_trade("NVDA", "Alice", "house_1", _days_ago(80))])
    scorer.score_cluster_trades([_trade("NVDA", "Bob", "house_2", _days_ago(50))])
    results = scorer.score_cluster_trades([_trade("NVDA", "Carol", "house_3", _days_ago(10))])

    assert "NVDA" in results
    pts, members = results["NVDA"]
    assert pts == scorer.POINTS_CLUSTER_3_PLUS
    assert set(members) == {"Alice", "Bob", "Carol"}


def test_malformed_history_file_does_not_crash(tmp_path, monkeypatch):
    history_file = tmp_path / "cluster_history.json"
    history_file.write_text("not valid json {{{")
    monkeypatch.setattr(scorer, "CLUSTER_HISTORY_FILE", str(history_file))
    monkeypatch.setattr(scorer, "DATA_DIR", str(tmp_path))

    results = scorer.score_cluster_trades([_trade("IBM", "Alice", "house_1", _days_ago(5))])
    assert results == {}  # just one member, no crash


def test_trades_without_ticker_or_representative_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(scorer, "CLUSTER_HISTORY_FILE", str(tmp_path / "cluster_history.json"))
    monkeypatch.setattr(scorer, "DATA_DIR", str(tmp_path))

    trades = [
        {"ticker": "", "representative": "Alice", "filing_id": "house_1", "transaction_date": _days_ago(5)},
        {"ticker": "ORCL", "representative": "", "filing_id": "house_2", "transaction_date": _days_ago(5)},
    ]
    results = scorer.score_cluster_trades(trades)
    assert results == {}
    assert scorer.load_cluster_history() == []
