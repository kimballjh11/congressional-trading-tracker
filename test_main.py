# test_main.py — Regression tests for main.py's pipeline step-gating logic.
#
# Bug: if enrich_trades() raised partway through (e.g. a transient network
# error or malformed XML response), main.py still called score_trades()
# unconditionally. Since enrich_trades() only overwrites
# ENRICHED_TRADES_FILE at the very end (after processing every trade), a
# failed enrichment run left that file holding whatever a PREVIOUS
# successful run wrote. score_trades() would then silently re-score and
# re-email that stale batch of already-reported trades, while the current
# run's genuinely new trades were never enriched, scored, or emailed at
# all — a duplicate-alert / silent-data-loss bug.

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import config


class TestMainPipelineGating(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_paths = (
            config.DATA_DIR,
            config.PARSED_TRADES_FILE,
            config.ENRICHED_TRADES_FILE,
            config.SCORED_TRADES_FILE,
            config.RUN_LOG_FILE,
        )
        config.DATA_DIR = self.tmpdir
        config.PARSED_TRADES_FILE = os.path.join(self.tmpdir, "parsed_trades.json")
        config.ENRICHED_TRADES_FILE = os.path.join(self.tmpdir, "enriched_trades.json")
        config.SCORED_TRADES_FILE = os.path.join(self.tmpdir, "scored_trades.json")
        config.RUN_LOG_FILE = os.path.join(self.tmpdir, "run_log.txt")

        # Reload main so it picks up the patched config module-level names
        # used inside enricher.py/scorer.py/main.py (all imported at call time).
        import importlib
        import main as main_mod
        importlib.reload(main_mod)
        self.main = main_mod

    def tearDown(self):
        (
            config.DATA_DIR,
            config.PARSED_TRADES_FILE,
            config.ENRICHED_TRADES_FILE,
            config.SCORED_TRADES_FILE,
            config.RUN_LOG_FILE,
        ) = self._orig_paths

    def _write_stale_enriched_file(self):
        stale_trade = {
            "representative": "Old Member",
            "ticker": "OLD",
            "asset": "Old stale trade",
            "transaction_type": "Purchase",
            "transaction_date": "01/01/2026",
            "notification_date": "01/10/2026",
            "amount": "$1,001 - $15,000",
            "owner": "",
            "description": "",
            "committees": [],
            "sector": "",
            "current_price": None,
            "industry": "",
            "filing_id": "house_STALE",
        }
        with open(config.ENRICHED_TRADES_FILE, "w") as f:
            json.dump([stale_trade], f)

    def _fresh_filing_and_parse_mock(self):
        fresh_filing = {
            "representative": "New Member",
            "state_district": "ZZ01",
            "year": "2026",
            "filing_type": "PTR",
            "filing_id": "house_FRESH",
            "pdf_url": "http://example.com/fresh.pdf",
            "chamber": "House",
        }

        def fake_parse(filings):
            fresh_trade = {
                "representative": "New Member",
                "ticker": "NEW",
                "filing_id": "house_FRESH",
            }
            with open(config.PARSED_TRADES_FILE, "w") as f:
                json.dump([fresh_trade], f)
            return [fresh_trade]

        return fresh_filing, fake_parse

    def test_enrich_failure_does_not_score_or_email_stale_data(self):
        """If enrichment raises, score_trades() must be skipped entirely —
        the stale enriched file from a prior run must never be re-scored
        or re-emailed."""
        self._write_stale_enriched_file()
        fresh_filing, fake_parse = self._fresh_filing_and_parse_mock()

        with patch("main.get_new_trades", return_value=[fresh_filing]), \
             patch("main.get_new_senate_trades", return_value=[]), \
             patch("main.parse_all_filings", side_effect=fake_parse), \
             patch("main.enrich_trades", side_effect=RuntimeError("simulated enrichment failure")), \
             patch("main.score_trades") as mock_score, \
             patch("main.send_report") as mock_send:

            self.main.run()

            mock_score.assert_not_called()
            mock_send.assert_called_once()
            scored_arg = mock_send.call_args[0][0]
            self.assertEqual(scored_arg, [])

        # The stale file on disk must be untouched — proves we never
        # treated it as this run's fresh data.
        with open(config.ENRICHED_TRADES_FILE) as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk[0]["filing_id"], "house_STALE")

    def test_enrich_success_still_scores_normally(self):
        """Sanity check: the happy path (enrichment succeeds) must still
        call score_trades() and email its result, unchanged."""
        fresh_filing, fake_parse = self._fresh_filing_and_parse_mock()

        with patch("main.get_new_trades", return_value=[fresh_filing]), \
             patch("main.get_new_senate_trades", return_value=[]), \
             patch("main.parse_all_filings", side_effect=fake_parse), \
             patch("main.enrich_trades", return_value=None), \
             patch("main.score_trades", return_value=[{"score": 90, "filing_id": "house_FRESH"}]) as mock_score, \
             patch("main.send_report", return_value=True) as mock_send:

            self.main.run()

            mock_score.assert_called_once()
            mock_send.assert_called_once()
            scored_arg = mock_send.call_args[0][0]
            self.assertEqual(scored_arg, [{"score": 90, "filing_id": "house_FRESH"}])


if __name__ == "__main__":
    unittest.main()
