"""Tests for scorer.py's score_committee_match() signal.

Real-world regression check: a member who sits on BOTH the Ways and
Means committee (broad tax-policy influence over every sector) AND a
sector-specific oversight committee should get BOTH bonuses, since they
are two independent signals of potential conflict of interest. Verified
against real, live House Clerk committee-assignment data (fetched
2026-10-28): Rep. Feenstra (Ways and Means + Agriculture) and Rep. Tenney
(Ways and Means + Science, Space, and Technology) are both real current
examples of this exact combination.
"""

import scorer
from config import POINTS_COMMITTEE_MATCH, POINTS_WAYS_AND_MEANS


def test_ways_and_means_only_still_scores():
    trade = {
        "committees": ["Committee on Ways and Means"],
        "sector": "Healthcare",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == POINTS_WAYS_AND_MEANS
    assert "Ways and Means" in reason


def test_sector_committee_only_still_scores():
    trade = {
        "committees": ["Committee on Energy and Commerce"],
        "sector": "Healthcare",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == POINTS_COMMITTEE_MATCH
    assert "Energy and Commerce" in reason


def test_ways_and_means_plus_sector_committee_both_score():
    """Regression test: both bonuses must accumulate, not short-circuit.

    Real example: Rep. Feenstra sits on both Ways and Means and
    Agriculture. A trade in a Consumer Staples/Materials stock (mapped to
    Agriculture) should score both the tax-policy bonus AND the direct
    sector-oversight bonus.
    """
    trade = {
        "committees": ["Committee on Agriculture", "Committee on Ways and Means"],
        "sector": "Consumer Staples",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == POINTS_WAYS_AND_MEANS + POINTS_COMMITTEE_MATCH
    assert "Ways and Means" in reason
    assert "Agriculture" in reason


def test_ways_and_means_plus_sector_committee_order_independent():
    """Same as above, but committees listed in the opposite order —
    confirms the fix isn't accidentally dependent on list ordering."""
    trade = {
        "committees": ["Committee on Ways and Means", "Committee on Science, Space, and Technology"],
        "sector": "Information Technology",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == POINTS_WAYS_AND_MEANS + POINTS_COMMITTEE_MATCH


def test_no_match_scores_zero():
    trade = {
        "committees": ["Committee on Education and Labor"],
        "sector": "Healthcare",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == 0
    assert reason == ""


def test_missing_committees_or_sector_scores_zero():
    assert scorer.score_committee_match({"committees": [], "sector": "Healthcare"}) == (0, "")
    assert scorer.score_committee_match({"committees": ["Committee on Ways and Means"], "sector": ""}) == (0, "")
