# test_scorer.py — Tests for scorer.py's cluster-trading signal
#
# Bug fixed: score_cluster_trades() previously only ever considered the
# trades passed to it in a single call. Since main.py calls it once per
# pipeline run with only that run's newly-scraped filings (parsed/enriched/
# scored JSON files are overwritten each run, not accumulated), two members
# who filed PTRs for the same ticker on different days — the overwhelmingly
# common case, since disclosure delays vary member to member — would never
# be detected as a "cluster", even though this is one of the codebase's
# highest-value suspicion signals (+15/+20 points).
#
# The fix persists a rolling window of (ticker, member, date) records to
# CLUSTER_HISTORY_FILE and merges it with each run's trades before counting
# distinct members per ticker.

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import scorer


class TestClusterTradesCrossRun(unittest.TestCase):
    def setUp(self):
        # Use a throwaway history file per test so tests don't interfere
        # with each other or with any real data/cluster_history.json.
        self.tmpdir = tempfile.mkdtemp()
        self.history_file = os.path.join(self.tmpdir, "cluster_history.json")
        self.patcher = patch("scorer.CLUSTER_HISTORY_FILE", self.history_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.history_file):
            os.remove(self.history_file)
        os.rmdir(self.tmpdir)

    def _date(self, days_ago):
        return (datetime.now() - timedelta(days=days_ago)).strftime("%m/%d/%Y")

    def test_same_batch_two_members_still_detected(self):
        """Regression: two members in the SAME run's batch must still cluster."""
        trades = [
            {"ticker": "NVDA", "representative": "Smith, Jane", "filing_id": "house_1",
             "transaction_date": self._date(1)},
            {"ticker": "NVDA", "representative": "Jones, Bob", "filing_id": "house_2",
             "transaction_date": self._date(1)},
        ]
        results = scorer.score_cluster_trades(trades)
        self.assertIn("NVDA", results)
        pts, members = results["NVDA"]
        self.assertEqual(pts, scorer.POINTS_CLUSTER_2)
        self.assertEqual(set(members), {"Smith, Jane", "Jones, Bob"})

    def test_cross_run_cluster_detected_via_history(self):
        """The actual bug: a member's trade recorded on a PREVIOUS run,
        combined with a different member's trade in TODAY's run, must be
        detected as a cluster even though they were never in the same
        score_cluster_trades() call."""
        day1_trades = [
            {"ticker": "NVDA", "representative": "Smith, Jane", "filing_id": "house_1",
             "transaction_date": self._date(5)},
        ]
        day1_results = scorer.score_cluster_trades(day1_trades)
        self.assertNotIn("NVDA", day1_results)  # only 1 member so far

        day2_trades = [
            {"ticker": "NVDA", "representative": "Jones, Bob", "filing_id": "house_2",
             "transaction_date": self._date(1)},
        ]
        day2_results = scorer.score_cluster_trades(day2_trades)
        self.assertIn("NVDA", day2_results)
        pts, members = day2_results["NVDA"]
        self.assertEqual(pts, scorer.POINTS_CLUSTER_2)
        self.assertEqual(set(members), {"Smith, Jane", "Jones, Bob"})

    def test_stale_history_pruned(self):
        """A member's trade older than CLUSTER_LOOKBACK_DAYS must not count
        toward today's cluster, and must be pruned from the saved history."""
        old_date = (datetime.now() - timedelta(days=scorer.CLUSTER_LOOKBACK_DAYS + 30)).strftime("%m/%d/%Y")
        history = [{
            "filing_id": "house_old", "ticker": "NVDA",
            "representative": "Old, Member", "transaction_date": old_date,
        }]
        with open(self.history_file, "w") as f:
            json.dump(history, f)

        trades = [
            {"ticker": "NVDA", "representative": "Jones, Bob", "filing_id": "house_2",
             "transaction_date": self._date(1)},
        ]
        results = scorer.score_cluster_trades(trades)
        self.assertNotIn("NVDA", results)  # only 1 fresh member, stale one dropped

        with open(self.history_file) as f:
            saved = json.load(f)
        self.assertNotIn("Old, Member", [r["representative"] for r in saved])

    def test_three_plus_members_across_runs(self):
        """3 different members across 3 separate runs should hit the
        higher +20 threshold, not just +15."""
        for i, member in enumerate(["Smith, Jane", "Jones, Bob", "Lee, Ann"]):
            trades = [{
                "ticker": "TSLA", "representative": member,
                "filing_id": f"house_{i}", "transaction_date": self._date(10 - i),
            }]
            results = scorer.score_cluster_trades(trades)

        pts, members = results["TSLA"]
        self.assertEqual(pts, scorer.POINTS_CLUSTER_3_PLUS)
        self.assertEqual(len(members), 3)

    def test_same_member_repeated_does_not_inflate_count(self):
        """The same member trading the same ticker across multiple runs
        (or twice in one run) must not be double-counted as 2 members."""
        trades_run1 = [
            {"ticker": "AAPL", "representative": "Smith, Jane", "filing_id": "house_1",
             "transaction_date": self._date(3)},
        ]
        scorer.score_cluster_trades(trades_run1)

        trades_run2 = [
            {"ticker": "AAPL", "representative": "Smith, Jane", "filing_id": "house_2",
             "transaction_date": self._date(1)},
        ]
        results = scorer.score_cluster_trades(trades_run2)
        self.assertNotIn("AAPL", results)  # still only 1 distinct member

    def test_trade_missing_ticker_or_member_ignored(self):
        trades = [
            {"ticker": "", "representative": "Smith, Jane", "filing_id": "house_1",
             "transaction_date": self._date(1)},
            {"ticker": "MSFT", "representative": "", "filing_id": "house_2",
             "transaction_date": self._date(1)},
        ]
        results = scorer.score_cluster_trades(trades)
        self.assertEqual(results, {})
        with open(self.history_file) as f:
            saved = json.load(f)
        self.assertEqual(saved, [])

    def test_no_history_file_on_first_run(self):
        """First-ever run (no cluster_history.json yet) shouldn't crash."""
        self.assertFalse(os.path.exists(self.history_file))
        results = scorer.score_cluster_trades([
            {"ticker": "AMZN", "representative": "Smith, Jane", "filing_id": "house_1",
             "transaction_date": self._date(1)},
        ])
        self.assertEqual(results, {})
        self.assertTrue(os.path.exists(self.history_file))


if __name__ == "__main__":
    unittest.main()
