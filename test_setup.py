"""Tests for setup.py's setup_linux_cron() — the daily cron installer.

Covers the "stale entry from a previous install at a different path" bug:
before the fix, the duplicate-install check was `"run_on_wake.py" in existing`
— a plain substring match across the whole crontab text. If the project
directory was ever moved or re-cloned to a new path, the OLD cron line
(pointing at the now-stale path) still contains the substring "run_on_wake.py",
so the check always reported "already installed" and never added the correct
line for the new path — silently leaving the daily automation permanently
broken with no error shown to the user.
"""

import subprocess
import unittest
from unittest import mock

import setup


class SetupLinuxCronTests(unittest.TestCase):
    def _run(self, existing_crontab, python_path="/home/user/repo/venv/bin/python"):
        """Run setup_linux_cron() with a mocked crontab, return (calls, cron_line)."""
        cron_line = (
            f"0 8 * * * cd {setup.PROJECT_DIR} && {python_path} "
            f"{setup.PROJECT_DIR}/run_on_wake.py >> {setup.DATA_DIR}/cron.log 2>&1"
        )

        list_result = mock.Mock(returncode=0, stdout=existing_crontab)
        install_result = mock.Mock(returncode=0, stderr="")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd == ["crontab", "-l"]:
                return list_result
            if cmd == ["crontab", "-"]:
                return install_result
            raise AssertionError(f"Unexpected subprocess.run call: {cmd}")

        with mock.patch.object(setup.subprocess, "run", side_effect=fake_run):
            setup.setup_linux_cron(python_path)

        return calls, cron_line

    def test_exact_match_already_installed_skips_reinstall(self):
        """Re-running from the SAME path with the exact line present must not touch crontab -."""
        cron_line = (
            f"0 8 * * * cd {setup.PROJECT_DIR} && /home/user/repo/venv/bin/python "
            f"{setup.PROJECT_DIR}/run_on_wake.py >> {setup.DATA_DIR}/cron.log 2>&1"
        )
        calls, _ = self._run(existing_crontab=cron_line + "\n")

        install_calls = [c for c in calls if c[0] == ["crontab", "-"]]
        self.assertEqual(install_calls, [], "should not reinstall when the exact line is already present")

    def test_stale_path_entry_is_replaced_not_treated_as_installed(self):
        """A leftover line from a DIFFERENT path must be replaced with the correct one, not skipped."""
        stale_line = (
            "0 8 * * * cd /home/user/OLD-repo && /home/user/OLD-repo/venv/bin/python "
            "/home/user/OLD-repo/run_on_wake.py >> /home/user/OLD-repo/data/cron.log 2>&1"
        )
        calls, cron_line = self._run(existing_crontab=stale_line + "\n")

        install_calls = [c for c in calls if c[0] == ["crontab", "-"]]
        self.assertEqual(len(install_calls), 1, "must actually install the corrected entry")
        new_crontab = install_calls[0][1]["input"]

        self.assertIn(cron_line, new_crontab)
        self.assertNotIn(stale_line, new_crontab)

    def test_unrelated_cron_jobs_are_preserved(self):
        """Installing/replacing our line must not disturb the user's other cron jobs."""
        unrelated = "0 3 * * * /usr/bin/some-other-job.sh"
        stale_line = (
            "0 8 * * * cd /home/user/OLD-repo && /home/user/OLD-repo/venv/bin/python "
            "/home/user/OLD-repo/run_on_wake.py >> /home/user/OLD-repo/data/cron.log 2>&1"
        )
        calls, cron_line = self._run(existing_crontab=f"{unrelated}\n{stale_line}\n")

        install_calls = [c for c in calls if c[0] == ["crontab", "-"]]
        new_crontab = install_calls[0][1]["input"]

        self.assertIn(unrelated, new_crontab)
        self.assertIn(cron_line, new_crontab)
        self.assertNotIn(stale_line, new_crontab)

    def test_fresh_install_with_no_existing_crontab(self):
        """Happy path: nothing installed yet, no crontab at all."""
        calls, cron_line = self._run(existing_crontab="")

        install_calls = [c for c in calls if c[0] == ["crontab", "-"]]
        self.assertEqual(len(install_calls), 1)
        self.assertIn(cron_line, install_calls[0][1]["input"])


if __name__ == "__main__":
    unittest.main()
