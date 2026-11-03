"""Tests for scorer.py's disclosure-delay signal (score_disclosure_delay)."""

import scorer


def test_violation_over_45_days_scores_highest_tier():
    """A disclosure filed >45 days late is a confirmed STOCK Act violation
    and must score MORE than a near-limit (38-45 day) disclosure, not less."""
    trade = {"transaction_date": "01/01/2026", "notification_date": "03/12/2026"}  # 70 days
    pts, reason = scorer.score_disclosure_delay(trade)
    assert pts == scorer.POINTS_DELAY_VIOLATION
    assert pts > scorer.POINTS_DELAY_NEAR_LIMIT
    assert "violation" in reason.lower()


def test_violation_tier_is_strictly_greater_than_near_limit_tier():
    assert scorer.POINTS_DELAY_VIOLATION > scorer.POINTS_DELAY_NEAR_LIMIT > scorer.POINTS_DELAY_LATE


def test_near_limit_38_to_45_days_unaffected():
    trade = {"transaction_date": "01/01/2026", "notification_date": "02/10/2026"}  # 40 days
    pts, reason = scorer.score_disclosure_delay(trade)
    assert pts == scorer.POINTS_DELAY_NEAR_LIMIT
    assert "near 45-day limit" in reason


def test_late_30_to_37_days_unaffected():
    trade = {"transaction_date": "01/01/2026", "notification_date": "02/02/2026"}  # 32 days
    pts, reason = scorer.score_disclosure_delay(trade)
    assert pts == scorer.POINTS_DELAY_LATE


def test_on_time_disclosure_scores_zero():
    trade = {"transaction_date": "01/01/2026", "notification_date": "01/15/2026"}  # 14 days
    pts, reason = scorer.score_disclosure_delay(trade)
    assert pts == 0
    assert reason == ""


def test_exactly_46_days_hits_violation_tier():
    """Boundary check: 46 days is the first day past the 45-day deadline."""
    trade = {"transaction_date": "01/01/2026", "notification_date": "02/16/2026"}  # 46 days
    pts, _ = scorer.score_disclosure_delay(trade)
    assert pts == scorer.POINTS_DELAY_VIOLATION


def test_exactly_45_days_still_near_limit_not_violation():
    trade = {"transaction_date": "01/01/2026", "notification_date": "02/15/2026"}  # 45 days
    pts, reason = scorer.score_disclosure_delay(trade)
    assert pts == scorer.POINTS_DELAY_NEAR_LIMIT
    assert "violation" not in reason.lower()


def test_missing_dates_scores_zero():
    assert scorer.score_disclosure_delay({}) == (0, "")


def test_negative_delay_scores_zero():
    """notification before transaction (bad data) should not score anything."""
    trade = {"transaction_date": "02/01/2026", "notification_date": "01/15/2026"}
    assert scorer.score_disclosure_delay(trade) == (0, "")
