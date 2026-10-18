# test_setup.py — tests for setup.py's stdin/EOFError handling
#
# Bug: setup.py's three input() call sites (ask_yes_no(), and the two
# direct input() calls in setup_env() for the Gmail address/app password)
# had no error handling around input(). Running setup.py with no
# interactive stdin available — e.g. piped from /dev/null, invoked over
# a non-tty SSH session, or driven by another script/CI job — raises a
# raw, unhandled EOFError and crashes the entire setup flow with a Python
# traceback instead of a clear message, even though the rest of the
# script (check_python(), setup_venv(), etc.) already fails with
# actionable guidance instead of raw tracebacks.

import shutil
import sys
from unittest.mock import patch

import pytest

import setup


def test_safe_input_returns_empty_string_on_eof(capsys):
    """safe_input() should not raise when input() hits EOF — it should
    print a short notice and return "" so callers can fall back."""
    with patch("builtins.input", side_effect=EOFError):
        result = setup.safe_input("Prompt: ")

    assert result == ""
    out = capsys.readouterr().out
    assert "stdin" in out.lower() or "no input" in out.lower()


def test_safe_input_returns_value_on_normal_input():
    """safe_input() should behave exactly like input() when stdin is
    available — no behavior change for the normal interactive case."""
    with patch("builtins.input", return_value="hello"):
        result = setup.safe_input("Prompt: ")

    assert result == "hello"


def test_safe_input_exits_cleanly_on_keyboard_interrupt(capsys):
    """A Ctrl-C during input() should exit cleanly, not propagate as a
    raw KeyboardInterrupt traceback."""
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit) as exc_info:
            setup.safe_input("Prompt: ")

    assert exc_info.value.code == 1
    assert "cancelled" in capsys.readouterr().out.lower()


def test_ask_yes_no_falls_back_to_default_on_eof():
    """ask_yes_no() must not crash when stdin is closed — it should use
    the caller-supplied default just like an empty interactive answer."""
    with patch("builtins.input", side_effect=EOFError):
        assert setup.ask_yes_no("Continue?", default="y") is True
        assert setup.ask_yes_no("Continue?", default="n") is False


def test_ask_yes_no_still_parses_real_answers():
    """Non-EOF behavior of ask_yes_no() must be unchanged."""
    with patch("builtins.input", return_value="yes"):
        assert setup.ask_yes_no("Continue?", default="n") is True
    with patch("builtins.input", return_value="no"):
        assert setup.ask_yes_no("Continue?", default="y") is False
    with patch("builtins.input", return_value=""):
        assert setup.ask_yes_no("Continue?", default="y") is True


def test_setup_env_does_not_crash_on_eof(tmp_path, capsys):
    """setup_env() must not raise EOFError when stdin is unavailable —
    it should fall through to the existing 'skip and copy .env.example'
    path, the same as if the user pressed Enter with no input."""
    env_example = tmp_path / ".env.example"
    env_example.write_text("GMAIL_ADDRESS=your_email@gmail.com\n")
    env_file = tmp_path / ".env"

    with patch("setup.PROJECT_DIR", str(tmp_path)), \
         patch("setup.ENV_FILE", str(env_file)), \
         patch("builtins.input", side_effect=EOFError):
        setup.setup_env()  # should not raise

    assert env_file.exists()
    assert env_file.read_text() == env_example.read_text()
    assert "no input available" in capsys.readouterr().out.lower()


def test_setup_env_happy_path_unaffected(tmp_path):
    """Normal interactive setup_env() behavior (real credentials
    entered) must be unchanged by the safe_input() wrapper."""
    env_file = tmp_path / ".env"

    with patch("setup.PROJECT_DIR", str(tmp_path)), \
         patch("setup.ENV_FILE", str(env_file)), \
         patch("builtins.input", side_effect=["me@example.com", "abcd efgh ijkl mnop"]):
        setup.setup_env()

    content = env_file.read_text()
    assert "GMAIL_ADDRESS=me@example.com" in content
    assert "GMAIL_APP_PASSWORD=abcd efgh ijkl mnop" in content


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
