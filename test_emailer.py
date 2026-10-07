# test_emailer.py — Tests for emailer.py's report-building functions
#
# Focus: build_report_body()'s "no noteworthy trades" short message hardcoded
# the routine-score cutoff as the literal text "25", instead of reading it
# from config.SCORE_NOTEWORTHY. README.md explicitly tells users to edit
# config.py's "Score thresholds" to customize when trades get flagged, so the
# moment SCORE_NOTEWORTHY is changed from its default of 26, this message
# becomes factually wrong about what the pipeline actually did.

import re

import config
import emailer


def test_no_noteworthy_message_uses_configured_threshold_when_customized(monkeypatch):
    """With a customized SCORE_NOTEWORTHY, the summary text must reflect it,
    not the old default of 25."""
    monkeypatch.setattr(config, "SCORE_NOTEWORTHY", 30)
    monkeypatch.setattr(emailer, "SCORE_NOTEWORTHY", 30)

    trades = [{"tag": "routine", "score": 27, "representative": "Rep X"}]
    body = emailer.build_report_body(trades, total_filings=1)

    assert "All scored below 30 (routine)." in body
    assert "All scored 25 or below" not in body


def test_no_noteworthy_message_matches_default_threshold():
    """With the current default config (SCORE_NOTEWORTHY = 26), the message
    should describe the actual routine cutoff (below 26), not a disconnected
    hardcoded number."""
    trades = []
    body = emailer.build_report_body(trades, total_filings=0)

    match = re.search(r"All scored below (\d+) \(routine\)\.", body)
    assert match, f"Expected dynamic threshold text, got: {body}"
    assert int(match.group(1)) == config.SCORE_NOTEWORTHY


def test_no_noteworthy_message_is_never_stale_regardless_of_config_value(monkeypatch):
    """The message text must always track config.SCORE_NOTEWORTHY exactly,
    for any configured value — not just the shipped default."""
    for threshold in (10, 26, 40, 75):
        monkeypatch.setattr(emailer, "SCORE_NOTEWORTHY", threshold)
        trades = [{"tag": "routine", "score": threshold - 1, "representative": "Rep X"}]
        html = emailer.build_report_body(trades, total_filings=1)
        assert f"All scored below {threshold} (routine)." in html
