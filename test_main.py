# test_main.py — Tests for main.py's pipeline orchestration and CI failure gating

import os
import unittest
from unittest.mock import patch

import main


class TestFinishGating(unittest.TestCase):
    """
    main.py's finish() helper decides whether a GitHub Actions run should be
    reported as failed. It must fail CI whenever something went wrong,
    not just when the final email literally failed to send.
    """

    def setUp(self):
        self._prev_gha = os.environ.get("GITHUB_ACTIONS")
        os.environ["GITHUB_ACTIONS"] = "true"

    def tearDown(self):
        if self._prev_gha is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = self._prev_gha

    def test_ci_fails_when_step_errors_even_if_email_sent(self):
        """
        Both scrapers raise, but the (misleading, empty-looking) email still
        sends successfully. Before the fix, run() returned normally here and
        GitHub Actions would report the run as green/successful despite the
        real pipeline failure.
        """
        with patch("main.get_new_trades", side_effect=RuntimeError("boom")), \
             patch("main.get_new_senate_trades", side_effect=RuntimeError("boom")), \
             patch("main.send_report", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                main.run()
            self.assertEqual(ctx.exception.code, 1)

    def test_ci_fails_when_parser_errors_even_if_email_sent(self):
        """Same failure class, but the exception happens in STEP 2 (parse)."""
        with patch("main.get_new_trades", return_value=[{"filing_id": "1"}]), \
             patch("main.get_new_senate_trades", return_value=[]), \
             patch("main.parse_all_filings", side_effect=RuntimeError("boom")), \
             patch("main.send_report", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                main.run()
            self.assertEqual(ctx.exception.code, 1)

    def test_ci_fails_when_scorer_errors_even_if_email_sent(self):
        """Same failure class, but the exception happens in STEP 4 (score)."""
        with patch("main.get_new_trades", return_value=[{"filing_id": "1"}]), \
             patch("main.get_new_senate_trades", return_value=[]), \
             patch("main.parse_all_filings", return_value=[{"ticker": "AAPL"}]), \
             patch("main.enrich_trades", return_value=None), \
             patch("main.score_trades", side_effect=RuntimeError("boom")), \
             patch("main.send_report", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                main.run()
            self.assertEqual(ctx.exception.code, 1)

    def test_ci_still_fails_when_email_not_sent(self):
        """Pre-existing behavior (PR #25) must still work: no errors upstream,
        but the final email itself fails to send."""
        with patch("main.get_new_trades", return_value=[]), \
             patch("main.get_new_senate_trades", return_value=[]), \
             patch("main.send_report", return_value=False):
            with self.assertRaises(SystemExit) as ctx:
                main.run()
            self.assertEqual(ctx.exception.code, 1)

    def test_ci_passes_on_a_fully_clean_run(self):
        """No errors anywhere and the email sends: CI must NOT fail."""
        with patch("main.get_new_trades", return_value=[]), \
             patch("main.get_new_senate_trades", return_value=[]), \
             patch("main.send_report", return_value=True):
            try:
                main.run()
            except SystemExit:
                self.fail("run() should not raise SystemExit on a clean run")

    def test_finish_is_a_noop_outside_github_actions(self):
        """Outside CI (e.g. a developer's laptop), errors must never crash the
        process via SystemExit — only the GitHub Actions gate should do that."""
        os.environ.pop("GITHUB_ACTIONS", None)
        with patch("main.get_new_trades", side_effect=RuntimeError("boom")), \
             patch("main.get_new_senate_trades", side_effect=RuntimeError("boom")), \
             patch("main.send_report", return_value=True):
            try:
                main.run()
            except SystemExit:
                self.fail("run() should not raise SystemExit outside GITHUB_ACTIONS")


if __name__ == "__main__":
    unittest.main()
