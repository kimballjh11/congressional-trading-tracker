# test_scorer.py — Tests for scorer.py's suspicion-scoring signals.
#
# Focus: score_committee_match() previously stopped scoring the moment it
# found a Ways and Means match, never checking whether the member ALSO sits
# on a sector-specific committee. Real members sit on both at once (e.g.
# Rep. Feenstra: Ways and Means + Agriculture; Rep. Tenney: Ways and Means +
# Science, Space, and Technology) — both signals should independently
# contribute points rather than the first one found winning exclusively.

import scorer


def test_ways_and_means_only_scores_ways_and_means_bonus():
    trade = {
        "committees": ["Committee on Ways and Means"],
        "sector": "Financial Services",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == 10
    assert "tax policy" in reason


def test_sector_committee_only_scores_sector_bonus():
    trade = {
        "committees": ["Committee on Financial Services"],
        "sector": "Financial Services",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == 25
    assert "tax policy" not in reason


def test_ways_and_means_plus_sector_committee_accumulates_both_bonuses():
    """Real-world case: Rep. Feenstra sits on Ways and Means AND Agriculture."""
    trade = {
        "committees": ["Committee on Agriculture", "Committee on Ways and Means"],
        "sector": "Consumer Staples",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == 35
    assert "tax policy" in reason
    assert "Committee on Agriculture" in reason


def test_ways_and_means_plus_unrelated_sector_scores_only_ways_and_means():
    """Ways and Means member whose OTHER committees don't relate to the
    stock's sector should only get the tax-policy bonus, not a sector
    bonus that doesn't actually apply."""
    trade = {
        "committees": ["Permanent Select Committee on Intelligence", "Committee on Ways and Means"],
        "sector": "Consumer Staples",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == 10
    assert "tax policy" in reason


def test_multiple_sector_matching_committees_only_scored_once():
    """A member on two committees both matching the same sector shouldn't
    be double-counted for what is effectively one signal."""
    trade = {
        "committees": ["Committee on Energy and Commerce", "Committee on Transportation"],
        "sector": "Energy",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == 25


def test_no_committees_or_sector_scores_zero():
    assert scorer.score_committee_match({"committees": [], "sector": "Energy"}) == (0, "")
    assert scorer.score_committee_match({"committees": ["Committee on Ways and Means"], "sector": ""}) == (0, "")


def test_no_match_scores_zero():
    trade = {
        "committees": ["Committee on Oversight"],
        "sector": "Energy",
    }
    points, reason = scorer.score_committee_match(trade)
    assert points == 0
    assert reason == ""
