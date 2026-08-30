# test_scorer.py — Unit tests for scorer.py
#
# Focus of this file: score_contrarian() returns a diagnostic "reason" string
# even when it scores 0 points (e.g. "AAPL +2.3% in prior 30 days (no
# signal)"), but score_trades()'s Signal-7 call site used to gate appending
# that reason on `if pts:` — making the diagnostic text unreachable dead
# code any time the signal didn't fire. Verifies the fix (`if reason:`).
# Run with: PYTHONPATH=/workspace python3 -m pytest test_scorer.py -v

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import scorer


class TestContrarianReasonSurfaced(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.enriched_file = os.path.join(self.tmp_dir, "enriched_trades.json")
        self.scored_file = os.path.join(self.tmp_dir, "scored_trades.json")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_trade(self, trade):
        with open(self.enriched_file, "w") as f:
            json.dump([trade], f)

    def test_no_signal_reason_included_when_zero_points(self):
        """A 'no signal' contrarian reason should still show up in the
        trade's reason text, even though it contributes 0 points."""
        trade = {
            "representative": "Test Member",
            "committees": [],
            "sector": "",
            "amount": "$1,001 - $15,000",
            "transaction_date": "",
            "notification_date": "",
            "owner": "",
            "description": "",
            "asset": "Test Corp",
            "ticker": "TEST",
        }
        self._write_trade(trade)

        with patch("scorer.ENRICHED_TRADES_FILE", self.enriched_file), \
             patch("scorer.SCORED_TRADES_FILE", self.scored_file), \
             patch("scorer.DATA_DIR", self.tmp_dir), \
             patch("scorer.score_contrarian", return_value=(0, "TEST +2.3% in prior 30 days (no signal)")):
            scored = scorer.score_trades()

        self.assertEqual(len(scored), 1)
        self.assertIn("no signal", scored[0]["reason"])
        self.assertEqual(scored[0]["score"], 0)

    def test_no_reason_still_produces_generic_message_when_nothing_fires(self):
        """When score_contrarian returns no reason at all (e.g. missing
        ticker/date), the generic 'No signals fired' message is unaffected."""
        trade = {
            "representative": "Test Member",
            "committees": [],
            "sector": "",
            "amount": "$1,001 - $15,000",
            "transaction_date": "",
            "notification_date": "",
            "owner": "",
            "description": "",
            "asset": "Test Corp",
            "ticker": "",
        }
        self._write_trade(trade)

        with patch("scorer.ENRICHED_TRADES_FILE", self.enriched_file), \
             patch("scorer.SCORED_TRADES_FILE", self.scored_file), \
             patch("scorer.DATA_DIR", self.tmp_dir), \
             patch("scorer.score_contrarian", return_value=(0, "")):
            scored = scorer.score_trades()

        self.assertEqual(len(scored), 1)
        self.assertIn("No signals fired", scored[0]["reason"])

    def test_contrarian_points_still_scored_when_signal_fires(self):
        """Points from a real contrarian signal should still be added to
        the total, in addition to the reason text being included."""
        trade = {
            "representative": "Test Member",
            "committees": [],
            "sector": "",
            "amount": "$1,001 - $15,000",
            "transaction_date": "",
            "notification_date": "",
            "owner": "",
            "description": "",
            "asset": "Test Corp",
            "ticker": "TEST",
        }
        self._write_trade(trade)

        with patch("scorer.ENRICHED_TRADES_FILE", self.enriched_file), \
             patch("scorer.SCORED_TRADES_FILE", self.scored_file), \
             patch("scorer.DATA_DIR", self.tmp_dir), \
             patch("scorer.score_contrarian",
                   return_value=(scorer.POINTS_CONTRARIAN_BUY, "Contrarian buy: TEST down 12.0% in prior 30 days (+10)")):
            scored = scorer.score_trades()

        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0]["score"], scorer.POINTS_CONTRARIAN_BUY)
        self.assertIn("Contrarian buy", scored[0]["reason"])


if __name__ == "__main__":
    unittest.main()
