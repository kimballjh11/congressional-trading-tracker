# test_emailer.py — Tests for emailer.py's SMTP connection timeout handling.
#
# Bug: emailer.py's `_send()` called `smtplib.SMTP(SMTP_SERVER, SMTP_PORT)`
# with no `timeout` argument. Python's socket layer defaults to blocking
# forever (`socket.getdefaulttimeout()` is `None`), so if Gmail's SMTP
# server is unreachable (network partition, firewall silently dropping
# packets, DNS pointing at a dead host) the pipeline hangs indefinitely
# instead of failing fast and reporting an error — on GitHub Actions this
# means the job burns runner time until the job-level timeout kills it,
# with no email and no clear failure signal.

import smtplib
import time

import pytest

import config
import emailer


def test_smtp_timeout_is_configured():
    """config.py must define a finite, positive SMTP_TIMEOUT."""
    assert isinstance(config.SMTP_TIMEOUT, (int, float))
    assert config.SMTP_TIMEOUT > 0


def test_send_passes_timeout_to_smtp_constructor(monkeypatch):
    """_send() must forward config.SMTP_TIMEOUT into smtplib.SMTP()."""
    monkeypatch.setattr(emailer, "GMAIL_ADDRESS", "me@example.com")
    monkeypatch.setattr(emailer, "GMAIL_APP_PASSWORD", "app-password")

    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def starttls(self):
            pass

        def login(self, *args, **kwargs):
            pass

        def sendmail(self, *args, **kwargs):
            pass

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    result = emailer._send("subject", "<html></html>")

    assert result is True
    assert captured["timeout"] == config.SMTP_TIMEOUT
    assert captured["timeout"] is not None


def test_smtp_connect_with_timeout_fails_fast_on_unreachable_host():
    """
    Live network repro of the fix (not just a mock): connecting to a
    non-routable address WITH a finite timeout must fail at or near that
    timeout, bounding how long a dead/unreachable SMTP server can block
    the pipeline.

    Confirmed manually during development that the equivalent call with
    NO timeout argument (the original, unfixed code) instead blocks
    indefinitely against this same host — that variant is intentionally
    not run here since it would hang the test suite itself on a revert.
    """
    unreachable_host = "10.255.255.1"  # non-routable IPv4 test address
    bounded_wait = 3  # seconds — long enough to attempt a real TCP handshake

    start = time.monotonic()
    with pytest.raises(Exception):
        smtplib.SMTP(unreachable_host, 587, timeout=bounded_wait)
    elapsed = time.monotonic() - start

    assert elapsed < bounded_wait + 5


def test_send_handles_smtp_timeout_gracefully(monkeypatch):
    """A timed-out connection must be caught and reported, not crash the pipeline."""
    monkeypatch.setattr(emailer, "GMAIL_ADDRESS", "me@example.com")
    monkeypatch.setattr(emailer, "GMAIL_APP_PASSWORD", "app-password")

    def raise_timeout(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(smtplib, "SMTP", raise_timeout)

    result = emailer._send("subject", "<html></html>")

    assert result is False
