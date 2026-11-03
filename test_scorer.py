"""Tests for scorer.py's score_spouse_dependent().

score_spouse_dependent() must recognize both:
  - House 2-letter owner codes (SP, DC, JT)
  - Senate full plain-English owner labels (Spouse, Child, Joint)

Confirmed live against real senate.gov PTR reports (and cross-checked
against two independent third-party sources) that Senate reports never
use "Dependent" or "Dependent Child" -- the real word is always "Child".
Without handling the Senate full-word labels, every Senate spouse/
dependent/joint trade silently scored 0 on this +10 signal.
"""

import pytest

from scorer import score_spouse_dependent
from config import POINTS_SPOUSE_DEPENDENT


class TestHouseOwnerCodes:
    """Regression guard: the pre-existing House 2-letter codes must keep working."""

    def test_sp_code(self):
        pts, reason = score_spouse_dependent({"owner": "SP", "description": "", "asset": ""})
        assert pts == POINTS_SPOUSE_DEPENDENT
        assert "Spouse" in reason

    def test_dc_code(self):
        pts, reason = score_spouse_dependent({"owner": "DC", "description": "", "asset": ""})
        assert pts == POINTS_SPOUSE_DEPENDENT
        assert "Dependent" in reason

    def test_jt_code(self):
        pts, reason = score_spouse_dependent({"owner": "JT", "description": "", "asset": ""})
        assert pts == POINTS_SPOUSE_DEPENDENT


class TestSenateOwnerLabels:
    """The real bug: Senate's full-word owner labels were never recognized."""

    @pytest.mark.parametrize("owner", ["Spouse", "SPOUSE", "spouse", " Spouse "])
    def test_senate_spouse_label(self, owner):
        pts, reason = score_spouse_dependent({"owner": owner, "description": "", "asset": ""})
        assert pts == POINTS_SPOUSE_DEPENDENT
        assert "Spouse" in reason

    @pytest.mark.parametrize("owner", ["Child", "CHILD", "child"])
    def test_senate_child_label(self, owner):
        pts, reason = score_spouse_dependent({"owner": owner, "description": "", "asset": ""})
        assert pts == POINTS_SPOUSE_DEPENDENT
        assert "Dependent" in reason

    @pytest.mark.parametrize("owner", ["Joint", "JOINT", "joint"])
    def test_senate_joint_label(self, owner):
        pts, reason = score_spouse_dependent({"owner": owner, "description": "", "asset": ""})
        assert pts == POINTS_SPOUSE_DEPENDENT

    def test_senate_never_uses_dependent_or_dependent_child_in_practice(self):
        """Documented for clarity: real Senate reports use "Child", not these
        guessed variants. Still accepted (harmless) in case an older report
        format ever renders differently, but this is not the live vocabulary."""
        for owner in ["Dependent", "Dependent Child", "Joint Tenant", "Joint Tenants"]:
            pts, _ = score_spouse_dependent({"owner": owner, "description": "", "asset": ""})
            assert pts == POINTS_SPOUSE_DEPENDENT


class TestNoFalsePositives:
    def test_self_owner_no_signal(self):
        pts, reason = score_spouse_dependent({"owner": "Self", "description": "", "asset": ""})
        assert pts == 0
        assert reason == ""

    def test_blank_owner_no_signal(self):
        pts, reason = score_spouse_dependent({"owner": "", "description": "", "asset": ""})
        assert pts == 0

    def test_unrelated_description_no_signal(self):
        pts, reason = score_spouse_dependent(
            {"owner": "", "description": "full transaction", "asset": "Apple Inc"}
        )
        assert pts == 0


class TestDescriptionFallback:
    def test_description_keyword_still_works(self):
        pts, reason = score_spouse_dependent(
            {"owner": "", "description": "Spouse account", "asset": ""}
        )
        assert pts == POINTS_SPOUSE_DEPENDENT


class TestRealCapturedSenateTrades:
    """Fixtures modeled on real, live-captured senate.gov PTR rows
    (Wyden/Amcor Spouse; Alphabet/Hasbro Child; a Joint-owned batch)."""

    @pytest.mark.parametrize(
        "owner,asset",
        [
            ("Spouse", "Amcor PLC"),
            ("Child", "Alphabet Inc"),
            ("Child", "Hasbro Inc"),
            ("Joint", "Raytheon Technologies Corp"),
            ("Joint", "NVIDIA Corp"),
        ],
    )
    def test_real_senate_rows_score_signal(self, owner, asset):
        pts, _ = score_spouse_dependent({"owner": owner, "description": "", "asset": asset})
        assert pts == POINTS_SPOUSE_DEPENDENT
