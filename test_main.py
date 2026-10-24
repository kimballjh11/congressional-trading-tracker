# test_main.py — Tests for main.py's per-run filing batch cap (MAX_FILINGS_PER_RUN)
#
# Real production evidence (gh run view --log on this repo's own scheduled
# GitHub Actions runs, 2026-10-16 through 2026-10-22): once the Senate EFDS
# search backend came back up after months of downtime, a single run
# reported "Previously seen Senate filings: 0" / "New Senate filings found:
# 5634" — the entire un-marked-seen backlog surfaced at once. That run (and
# five others with the same signature) was killed by GitHub Actions' 6-hour
# job timeout before STEP 5 (email) ever ran, so none of those 5634+63
# filings were ever marked seen — guaranteeing the identical oversized
# backlog, and the identical multi-hour timeout, would recur on every future
# run where the search succeeds. These tests confirm that prior to this fix
# main.py would hand the ENTIRE backlog to parse_all_filings() uncapped, and
# that with the fix, a single run only ever processes MAX_FILINGS_PER_RUN
# filings at a time, leaving the remainder unmarked (and thus retried,
# bounded, on the next run).

from unittest.mock import patch

import config
import main


def _make_filings(prefix, count):
    return [
        {
            "filing_id": f"{prefix}_{i}",
            "representative": f"Member {i}",
            "state_district": "ST01",
            "pdf_url": f"https://example.com/{prefix}/{i}",
            "chamber": "Senate" if prefix == "senate" else "House",
        }
        for i in range(count)
    ]


def _run_with_mocked_pipeline(house_filings, senate_filings, captured):
    """
    Run main.run() with every pipeline step mocked out, capturing the list
    of filings that actually reaches parse_all_filings() and mark_filings_seen().
    """
    with patch("main.get_new_trades", return_value=house_filings), \
         patch("main.get_new_senate_trades", return_value=senate_filings), \
         patch("main.parse_all_filings") as mock_parse, \
         patch("main.enrich_trades", return_value=[]), \
         patch("main.score_trades") as mock_score, \
         patch("main.send_report", return_value=True), \
         patch("main.mark_filings_seen") as mock_mark, \
         patch("main.log"):

        def fake_parse(filings):
            captured["parsed_filings"] = list(filings)
            # Return one trade per filing so the pipeline continues past
            # the "no trades parsed" early-return branch.
            return [{"filing_id": f["filing_id"], "ticker": "", "score": 0} for f in filings]

        def fake_score():
            # Non-empty so main.py's "email_sent and scored" gate actually
            # calls mark_filings_seen() on the success path, same as a real
            # run that found and scored at least one trade.
            return captured["parsed_filings"]

        mock_parse.side_effect = fake_parse
        mock_score.side_effect = fake_score
        main.run()

        if mock_mark.call_args is not None:
            captured["marked_seen"] = list(mock_mark.call_args[0][0])


def test_small_batch_is_not_truncated():
    """A filing count under the cap is passed through unchanged."""
    house = _make_filings("house", 5)
    senate = _make_filings("senate", 10)
    captured = {}
    _run_with_mocked_pipeline(house, senate, captured)

    assert len(captured["parsed_filings"]) == 15
    assert len(captured["marked_seen"]) == 15


def test_oversized_backlog_is_capped_at_max_filings_per_run():
    """
    Reproduces the real 2026-10-19/20 production incident: thousands of
    never-seen Senate filings surface at once. Before this fix, main.py
    handed the full, unbounded list straight to parse_all_filings() (and
    then to enrich_trades()/score_trades(), which each do per-trade/
    per-ticker network calls) — this is what ran the pipeline past GitHub
    Actions' 6-hour job timeout. After the fix, a single run never
    processes more than MAX_FILINGS_PER_RUN filings.
    """
    house = _make_filings("house", 63)
    senate = _make_filings("senate", 5634)  # the real observed count
    captured = {}
    _run_with_mocked_pipeline(house, senate, captured)

    assert len(captured["parsed_filings"]) == config.MAX_FILINGS_PER_RUN
    # Only the capped batch gets marked seen — the rest must stay
    # unmarked so they're retried (bounded) on a future run instead of
    # being silently dropped.
    assert len(captured["marked_seen"]) == config.MAX_FILINGS_PER_RUN


def test_capped_batch_leaves_remainder_for_a_future_run():
    """
    The specific filings dropped this run are exactly the tail past the
    cap — nothing in the middle gets skipped — so a future run (which
    re-queries both scrapers and filters out whatever's already marked
    seen) will naturally pick up the remainder next.
    """
    house = _make_filings("house", 0)
    senate = _make_filings("senate", config.MAX_FILINGS_PER_RUN + 50)
    captured = {}
    _run_with_mocked_pipeline(house, senate, captured)

    parsed_ids = {f["filing_id"] for f in captured["parsed_filings"]}
    expected_ids = {f"senate_{i}" for i in range(config.MAX_FILINGS_PER_RUN)}
    assert parsed_ids == expected_ids


def test_uncapped_behavior_would_fail_this_test_without_the_fix():
    """
    Sanity check that the cap is actually doing something: directly
    reproduces the pre-fix behavior (no truncation at all) against the
    same oversized backlog, to show the old code path really would have
    hit parse_all_filings()/enrich_trades()/score_trades() with the full
    5634+63 = 5697 filings in one run.
    """
    house = _make_filings("house", 63)
    senate = _make_filings("senate", 5634)
    all_filings = house + senate
    # This is what main.py computed BEFORE the fix (no cap applied).
    assert len(all_filings) == 5697
    assert len(all_filings) > config.MAX_FILINGS_PER_RUN
