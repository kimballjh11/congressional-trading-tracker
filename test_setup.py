# test_setup.py — tests for setup.py's subprocess-failure handling
#
# Bug: setup.py called subprocess.run(..., check=True) for venv creation,
# pip install, and (on macOS) launchctl load without catching
# subprocess.CalledProcessError. Any failure in those steps (e.g. the very
# common "python3-venv package not installed" case on fresh Debian/Ubuntu
# systems) crashed setup.py with a raw Python traceback instead of a clear,
# actionable error message — a bad first impression for a script whose only
# job is friendly first-time setup.

import subprocess
import sys
from unittest.mock import patch, MagicMock

import pytest

import setup


def test_setup_venv_creation_failure_exits_cleanly(capsys):
    """venv creation failing (e.g. missing python3-venv) should print
    actionable guidance and exit cleanly, not raise CalledProcessError."""
    with patch("setup.os.path.exists", return_value=False), \
         patch("setup.platform.system", return_value="Linux"), \
         patch.object(setup.subprocess, "run",
                       side_effect=subprocess.CalledProcessError(1, "venv")):
        with pytest.raises(SystemExit) as exc_info:
            setup.setup_venv()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "venv" in out.lower()
    assert "apt install" in out


def test_setup_venv_pip_install_failure_exits_cleanly(capsys):
    """pip install failing (e.g. no network) should print actionable
    guidance and exit cleanly instead of crashing with a raw traceback."""
    def run_side_effect(cmd, check=False):
        if cmd[0] == sys.executable:
            return MagicMock()
        raise subprocess.CalledProcessError(1, cmd)

    with patch("setup.os.path.exists", return_value=False), \
         patch.object(setup.subprocess, "run", side_effect=run_side_effect):
        with pytest.raises(SystemExit) as exc_info:
            setup.setup_venv()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "requirements.txt" in out


def test_setup_venv_happy_path_returns_python_path():
    """When both subprocess calls succeed, setup_venv() should return the
    venv's python path without raising."""
    with patch("setup.os.path.exists", return_value=True), \
         patch.object(setup.subprocess, "run", return_value=MagicMock()) as mock_run:
        python_path = setup.setup_venv()

    # venv already exists, so only pip install should be invoked
    assert mock_run.call_count == 1
    assert python_path.endswith(
        "python" if setup.platform.system() != "Windows" else "python.exe"
    )


def test_setup_macos_launchagent_load_failure_handled_gracefully(tmp_path, monkeypatch, capsys):
    """launchctl load failing should print guidance and return, not raise."""
    monkeypatch.setenv("HOME", str(tmp_path))

    def run_side_effect(cmd, check=False, capture_output=False):
        if cmd[:2] == ["launchctl", "load"]:
            raise subprocess.CalledProcessError(1, cmd)
        return MagicMock(returncode=0)

    with patch.object(setup.subprocess, "run", side_effect=run_side_effect):
        # Should not raise
        setup.setup_macos_launchagent("/fake/venv/bin/python")

    out = capsys.readouterr().out
    assert "Failed to load the LaunchAgent" in out
    assert "launchctl load" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
