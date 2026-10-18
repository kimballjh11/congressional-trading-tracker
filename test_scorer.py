# test_scorer.py — Tests for scorer.py's committee/sector match signal
#
# Background: config.py's COMMITTEE_SECTOR_MAP previously used GICS-style
# sector names ("Information Technology", "Consumer Discretionary",
# "Consumer Staples", "Materials"), but yfinance's `Ticker.info["sector"]`
# never returns those strings — it uses its own taxonomy ("Technology",
# "Consumer Cyclical", "Consumer Defensive", "Basic Materials"). Since
# score_committee_match() does an exact `sector in sectors` membership
# check, this silently broke the +25-point committee/sector match signal
# (the highest-value signal in the whole scoring system) for any trade
# whose sector fell into one of those four mismatched categories —
# confirmed live against 857 real 2026 House trades: 35 trades that should
# have matched (e.g. a Science, Space, and Technology committee member
# trading a "Technology"-sector stock like AAPL) scored 0 points instead.

import unittest
import scorer


class TestCommitteeSectorMatch(unittest.TestCase):
    def test_science_committee_matches_yfinance_technology_sector(self):
        trade = {
            "committees": ["Committee on Science, Space, and Technology"],
            "sector": "Technology",
        }
        pts, reason = scorer.score_committee_match(trade)
        self.assertEqual(pts, scorer.POINTS_COMMITTEE_MATCH)
        self.assertIn("Technology", reason)

    def test_energy_and_commerce_matches_consumer_cyclical(self):
        trade = {
            "committees": ["Committee on Energy and Commerce"],
            "sector": "Consumer Cyclical",
        }
        pts, reason = scorer.score_committee_match(trade)
        self.assertEqual(pts, scorer.POINTS_COMMITTEE_MATCH)

    def test_agriculture_matches_consumer_defensive(self):
        trade = {
            "committees": ["Committee on Agriculture"],
            "sector": "Consumer Defensive",
        }
        pts, reason = scorer.score_committee_match(trade)
        self.assertEqual(pts, scorer.POINTS_COMMITTEE_MATCH)

    def test_agriculture_matches_basic_materials(self):
        trade = {
            "committees": ["Committee on Agriculture"],
            "sector": "Basic Materials",
        }
        pts, reason = scorer.score_committee_match(trade)
        self.assertEqual(pts, scorer.POINTS_COMMITTEE_MATCH)

    def test_old_gics_style_sector_names_no_longer_used(self):
        # Sanity check that the old, wrong GICS-style names aren't
        # anywhere in the map anymore (they'd never match a real
        # yfinance sector string, silently zeroing the signal).
        stale_names = {
            "Information Technology",
            "Consumer Discretionary",
            "Consumer Staples",
            "Materials",
        }
        all_mapped_sectors = {
            s for sectors in scorer.COMMITTEE_SECTOR_MAP.values() for s in sectors
        }
        self.assertFalse(all_mapped_sectors & stale_names)

    def test_unrelated_committee_and_sector_still_scores_zero(self):
        trade = {
            "committees": ["Committee on House Administration"],
            "sector": "Technology",
        }
        pts, reason = scorer.score_committee_match(trade)
        self.assertEqual(pts, 0)

    def test_no_committees_or_sector_scores_zero(self):
        self.assertEqual(scorer.score_committee_match({})[0], 0)
        self.assertEqual(
            scorer.score_committee_match({"committees": ["Committee on Agriculture"]})[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
