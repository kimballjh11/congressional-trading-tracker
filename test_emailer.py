# test_emailer.py — Tests for emailer.py's routine-trade double-counting bug.
#
# Bug: build_report_body() tallies `routine_count` once per trade inside
# the tier-bucketing loop (every trade not in `tier_buckets` — i.e. every
# routine trade — hits the `else: routine_count += 1` branch), then adds
# `len(scored_trades) - flagged` on top of that AFTER the loop. Since
# `len(scored_trades) - flagged` is exactly the same set of routine trades
# already counted in the loop, every real routine trade gets counted
# TWICE in the "N routine (not shown)" summary line shown in the actual
# emailed report.

import re

import emailer


def _trade(tag, **overrides):
    base = {
        "tag": tag,
        "score": 10,
        "representative": "Rep. Example",
        "ticker": "XYZ",
        "transaction_type": "Purchase",
        "amount": "$1,001 - $15,000",
        "transaction_date": "01/01/2026",
        "notification_date": "01/10/2026",
        "reason": "test reason",
    }
    base.update(overrides)
    return base


def _routine_count_shown(body):
    match = re.search(r"<strong>(\d+)</strong> routine", body)
    assert match, "summary line with routine count not found in email body"
    return int(match.group(1))


def test_routine_trades_are_not_double_counted():
    trades = [
        _trade("high_alert", score=90),
        _trade("routine", score=10),
        _trade("routine", score=5),
    ]
    body = emailer.build_report_body(trades, total_filings=3)
    assert _routine_count_shown(body) == 2


def test_routine_count_with_mixed_tiers_and_many_routine_trades():
    trades = (
        [_trade("high_alert", score=90)]
        + [_trade("suspicious", score=60)] * 2
        + [_trade("noteworthy", score=30)] * 3
        + [_trade("routine", score=5)] * 7
    )
    body = emailer.build_report_body(trades, total_filings=20)
    assert _routine_count_shown(body) == 7


def test_zero_routine_trades_shows_zero_not_negative_or_doubled():
    trades = [_trade("high_alert", score=90), _trade("suspicious", score=60)]
    body = emailer.build_report_body(trades, total_filings=2)
    assert _routine_count_shown(body) == 0


def test_unrecognized_tag_falls_back_to_routine_bucket_exactly_once():
    # A trade with a tag that doesn't match any configured EMAIL_TIER
    # (e.g. drift between scorer.py and config.py) should still land in
    # the routine bucket exactly once, not twice.
    trades = [
        _trade("high_alert", score=90),
        _trade("some_unknown_tag", score=15),
    ]
    body = emailer.build_report_body(trades, total_filings=2)
    assert _routine_count_shown(body) == 1
