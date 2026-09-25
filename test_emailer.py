# test_emailer.py — Regression tests for emailer.py's failure visibility.
#
# Covers a real, live-reproduced bug: when a pipeline step (scraper, parser,
# enricher, scorer) raised an exception, main.py correctly logged an
# "ERROR ..." line to data/run_log.txt and marked the run "PARTIAL" — but
# the actual email sent to the user was indistinguishable from a genuinely
# successful, quiet day. Two concrete cases:
#
#   1. Both scrapers fail -> all_filings is empty -> the email says
#      "No new congressional trade filings today. The pipeline checked
#      House and Senate disclosure sites and found no new PTR filings"
#      even though nothing was actually checked.
#   2. The parser step crashes entirely -> trades is empty -> the email
#      says "Scanned N filing(s), 0 trade(s) extracted. All scored 25 or
#      below (routine)." even though nothing was ever scored.
#
# Since the email is this tool's only user-facing surface (most users never
# look at data/run_log.txt or CI logs), a failed run looked identical to a
# clean one — a real outage could persist indefinitely, unnoticed.
#
# Fixed by threading an `errors` list from main.py through send_report()
# into build_no_filings_body()/build_report_body()/build_subject(), which
# now render a visible warning banner and avoid asserting things ("checked
# the sites", "all scored 25 or below") that didn't actually happen.

import emailer


def test_no_filings_body_without_errors_unchanged():
    """Regression guard: a genuinely quiet day's copy is unchanged."""
    body = emailer.build_no_filings_body(errors=[])
    assert "No new congressional trade filings today." in body
    assert "checked House and Senate disclosure sites" in body
    assert "Pipeline error" not in body


def test_no_filings_body_with_errors_flags_failure():
    """When scraping failed outright, the email must say so, not claim a clean check."""
    body = emailer.build_no_filings_body(errors=["House scraper failed: 503"])
    assert "Pipeline errors prevented a full check" in body
    assert "House scraper failed: 503" in body
    # Must NOT claim the sites were successfully checked when they weren't.
    assert "found no new PTR filings" not in body


def test_report_body_zero_trades_without_errors_unchanged():
    """Regression guard: 0 trades because they were genuinely routine is unchanged."""
    body = emailer.build_report_body([], total_filings=3, errors=[])
    assert "All scored 25 or below (routine)." in body
    assert "Pipeline error" not in body


def test_report_body_zero_trades_with_errors_does_not_fabricate_scoring():
    """When the parser crashed, don't claim trades were scored 'routine'."""
    body = emailer.build_report_body([], total_filings=1, errors=["Parser failed: boom"])
    assert "Pipeline error" in body
    assert "Parser failed: boom" in body
    # The old copy implied real scoring happened — it must not appear here.
    assert "All scored 25 or below (routine)." not in body
    assert "no trades could be scored this run due to the error" in body


def test_report_body_with_flagged_trades_still_shows_error_banner():
    """A failed enrichment/scorer step must still surface, even alongside real flagged trades."""
    trades = [{
        "representative": "Doe, Jane", "asset": "Acme Corp", "ticker": "ACME",
        "transaction_type": "Purchase", "amount": "$50,001 - $100,000",
        "transaction_date": "01/01/2026", "notification_date": "01/10/2026",
        "score": 80, "tag": "high_alert", "reason": "test", "committees": [],
    }]
    body = emailer.build_report_body(trades, total_filings=1, errors=["Enricher failed: timeout"])
    assert "Pipeline error" in body
    assert "Enricher failed: timeout" in body
    assert "High Alert" in body  # the real flagged trade section still renders


def test_error_banner_escapes_html_in_error_messages():
    """Error text ultimately comes from str(exception) and could contain untrusted data."""
    body = emailer.build_error_banner(["<script>alert(1)</script>"])
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_build_subject_adds_warning_prefix_only_when_errors_present():
    assert emailer.build_subject([], no_new_filings=True, has_errors=False).startswith(
        "Congressional Trade Alert"
    )
    subject = emailer.build_subject([], no_new_filings=True, has_errors=True)
    assert subject.startswith("\u26a0")
    assert "No new filings" in subject


def test_send_report_passes_errors_through_to_body(monkeypatch):
    """End-to-end: send_report's `errors` kwarg must reach the actual email body/subject."""
    captured = {}

    def fake_send(subject, body):
        captured["subject"] = subject
        captured["body"] = body
        return True

    monkeypatch.setattr(emailer, "_send", fake_send)

    emailer.send_report([], no_new_filings=True, errors=["Senate scraper failed: 503"])

    assert captured["subject"].startswith("\u26a0")
    assert "Senate scraper failed: 503" in captured["body"]


def test_send_report_no_errors_regression():
    """Regression guard: omitting `errors` entirely still works exactly as before."""
    calls = {}

    def fake_send(subject, body):
        calls["subject"] = subject
        calls["body"] = body
        return True

    import unittest.mock
    with unittest.mock.patch.object(emailer, "_send", fake_send):
        emailer.send_report([], no_new_filings=True)

    assert not calls["subject"].startswith("\u26a0")
    assert "Pipeline error" not in calls["body"]
