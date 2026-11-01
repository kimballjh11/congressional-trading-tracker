# test_scorer.py — Regression tests for scorer.py's committee/sector match signal.
#
# Context: config.COMMITTEE_SECTOR_MAP previously used GICS-style sector
# names ("Information Technology", "Consumer Discretionary", "Consumer
# Staples", "Materials") that don't match yfinance's actual `info["sector"]`
# taxonomy ("Technology", "Consumer Cyclical", "Consumer Defensive",
# "Basic Materials"). This silently prevented the +25-point
# committee/sector match signal from ever firing for the Science/Technology,
# Agriculture, and part of the Energy and Commerce committee mappings, even
# though real members on those committees frequently trade stocks in those
# exact real-world sectors (confirmed live: 40 House members sit on the
# Science committee, 53 on Agriculture, 54 on Energy and Commerce).

import config
from scorer import score_committee_match


def test_science_committee_matches_real_technology_sector():
    """Science/Tech committee member trading a real 'Technology'-sector stock (e.g. NVDA/AAPL/MSFT)."""
    trade = {
        "committees": ["Committee on Science, Space, and Technology"],
        "sector": "Technology",
    }
    pts, reason = score_committee_match(trade)
    assert pts == config.POINTS_COMMITTEE_MATCH
    assert "Technology" in reason


def test_agriculture_committee_matches_real_consumer_defensive_sector():
    """Agriculture committee member trading a real 'Consumer Defensive'-sector stock (e.g. KO/WMT)."""
    trade = {
        "committees": ["Committee on Agriculture"],
        "sector": "Consumer Defensive",
    }
    pts, reason = score_committee_match(trade)
    assert pts == config.POINTS_COMMITTEE_MATCH


def test_agriculture_committee_matches_real_basic_materials_sector():
    """Agriculture committee member trading a real 'Basic Materials'-sector stock (e.g. FCX/LIN)."""
    trade = {
        "committees": ["Committee on Agriculture"],
        "sector": "Basic Materials",
    }
    pts, reason = score_committee_match(trade)
    assert pts == config.POINTS_COMMITTEE_MATCH


def test_energy_and_commerce_matches_real_consumer_cyclical_sector():
    """Energy and Commerce committee member trading a real 'Consumer Cyclical'-sector stock (e.g. AMZN/HD)."""
    trade = {
        "committees": ["Committee on Energy and Commerce"],
        "sector": "Consumer Cyclical",
    }
    pts, reason = score_committee_match(trade)
    assert pts == config.POINTS_COMMITTEE_MATCH


def test_old_gics_style_sector_names_no_longer_present_in_map():
    """The old, non-matching GICS-style names should not linger anywhere in the map."""
    all_sectors = {s for sectors in config.COMMITTEE_SECTOR_MAP.values() for s in sectors}
    assert "Information Technology" not in all_sectors
    assert "Consumer Discretionary" not in all_sectors
    assert "Consumer Staples" not in all_sectors
    assert "Materials" not in all_sectors


def test_unrelated_committee_sector_combo_still_scores_zero():
    """Sanity check: an unrelated committee/sector combo should not match."""
    trade = {
        "committees": ["Committee on Armed Services"],
        "sector": "Healthcare",
    }
    pts, reason = score_committee_match(trade)
    assert pts == 0
