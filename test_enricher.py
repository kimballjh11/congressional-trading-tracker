# test_enricher.py — Regression tests for enricher.py's committee-matching logic

import unittest

from enricher import find_committees_for_member


class TestFindCommitteesForMember(unittest.TestCase):
    def setUp(self):
        # A House member and a Senator who happen to share a last name.
        self.house_comms = {
            "Scott, Austin|GA08": ["House Armed Services"],
        }
        self.senate_comms = {
            "Scott, Tim|SC": ["Senate Finance"],
        }

    def test_exact_house_match(self):
        result = find_committees_for_member(
            self.house_comms, self.senate_comms,
            "Scott, Austin", "GA08", "House",
        )
        self.assertEqual(result, ["House Armed Services"])

    def test_exact_senate_match(self):
        result = find_committees_for_member(
            self.house_comms, self.senate_comms,
            "Scott, Tim", "SC", "Senate",
        )
        self.assertEqual(result, ["Senate Finance"])

    def test_last_name_fallback_does_not_cross_chambers_for_house_trade(self):
        # Representative name/state_district don't match exactly (e.g. XML
        # formatting differs slightly), so this falls through to the
        # last-name-only fallback. Since chamber="House", it must only
        # consider house_comms and must NOT return the Senator's committees.
        result = find_committees_for_member(
            self.house_comms, self.senate_comms,
            "Scott, A. Austin", "GA08", "House",
        )
        self.assertEqual(result, ["House Armed Services"])

    def test_last_name_fallback_does_not_cross_chambers_for_senate_trade(self):
        result = find_committees_for_member(
            self.house_comms, self.senate_comms,
            "Scott, Timothy", "SC", "Senate",
        )
        self.assertEqual(result, ["Senate Finance"])

    def test_state_abbr_fallback_not_applied_to_house_trade(self):
        # A House trade's state_district ("GA08") shares its first two
        # characters with no senator here, but verify the House chamber
        # trade never even attempts the Senate state-abbreviation fallback
        # by using a district whose prefix collides with a different
        # senator's state abbreviation, ensuring only house_comms is used.
        house_comms = {
            "Jones, Sam|SC01": ["House Judiciary"],
        }
        senate_comms = {
            "Jones, Pat|SC": ["Senate Judiciary"],
        }
        result = find_committees_for_member(
            house_comms, senate_comms,
            "Jones, Sam A.", "SC01", "House",
        )
        # Must match the House member via last-name fallback, not the
        # Senator via the (chamber-inappropriate) state-abbreviation path.
        self.assertEqual(result, ["House Judiciary"])

    def test_unknown_chamber_falls_back_to_both(self):
        # Legacy/best-effort behavior when chamber isn't provided at all.
        result = find_committees_for_member(
            self.house_comms, self.senate_comms,
            "Scott, Austin", "GA08",
        )
        self.assertEqual(result, ["House Armed Services"])

    def test_last_name_fallback_no_longer_leaks_house_committees_into_senate_trade(self):
        # Regression test for a real bug: when a Senate trade's office field
        # doesn't exactly match senate_comms' key format (e.g. a full state
        # name like "South Carolina" instead of a 2-letter abbreviation —
        # still unconfirmed live, see backlog notes), both the exact and
        # state-abbreviation matches fail and it falls through to the
        # last-name-only fallback. In the old (unscoped) implementation,
        # merging house_comms first then senate_comms into one dict meant
        # a House member sharing the same last name always won that
        # fallback lookup, silently attributing the House member's
        # committees to the Senator's trade.
        result = find_committees_for_member(
            self.house_comms, self.senate_comms,
            "Scott, Timothy", "South Carolina", "Senate",
        )
        self.assertEqual(result, ["Senate Finance"])

    def test_no_match_returns_empty_list(self):
        result = find_committees_for_member(
            self.house_comms, self.senate_comms,
            "Nobody, No One", "ZZ99", "House",
        )
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
