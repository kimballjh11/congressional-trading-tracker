# test_scorer.py — Regression tests for scorer.py's score_spouse_dependent()
#
# Bug: on unmodified main, score_spouse_dependent() only recognizes the
# House PDF owner codes "SP"/"DC"/"JT". Senate eFD HTML reports label the
# exact same ownership types with full words in the report's "Owner"
# column instead — but the real words are "Spouse", "Child", and "Joint",
# NOT codes. Since the House codes never match those words, every single
# Senate trade made through a spouse, dependent-child, or joint account
# was silently scored 0 for this signal, even though this is precisely
# the kind of proxy trading (STOCK Act "SP"/"DC"/"JT" equivalent) the
# signal exists to flag.
#
# The real-word vocabulary below was confirmed two ways:
#   1. Live HTTP fetches of real Senate PTR report pages via
#      senate_scraper.create_session() + parser.parse_senate_html()
#      against three known real UUIDs (see AGENT_MEMORIES for the exact
#      UUIDs) — the parsed "owner" field literally comes back as
#      "Spouse" (Wyden/Berry Global-Amcor exchange), "Child" (x2, an
#      Alphabet purchase and a Hasbro note purchase), and "Joint" (x10,
#      a batch of trades across Raytheon/Nvidia/Meta/etc).
#   2. Independent third-party documentation (a public Apify Senate eFD
#      scraper's own worked example against the same Wyden/Amcor report,
#      and a public Senate-trade-tracker's field description) both state
#      the Owner field renders as one of "Self", "Spouse", "Joint", or
#      "Child" — never "Dependent" or "Dependent Child".
#
# This fix is orthogonal to (and corrects a factual error in) the
# open-but-unmerged PR #3, which also touches score_spouse_dependent()
# but guesses the Senate label is "Dependent"/"Dependent Child" rather
# than the real "Child" — none of PR #3's own tests exist to catch this,
# and its guessed labels do not match any real Senate report.

import pytest

from scorer import score_spouse_dependent, score_trades
from config import POINTS_SPOUSE_DEPENDENT


def _trade(owner="", description="", asset="Some Stock"):
    return {
        "owner": owner,
        "description": description,
        "asset": asset,
        "representative": "Test Member",
        "ticker": "TST",
    }


# ─── House PDF owner codes (regression guard — must keep working) ───

def test_house_spouse_code_sp():
    pts, reason = score_spouse_dependent(_trade(owner="SP"))
    assert pts == POINTS_SPOUSE_DEPENDENT
    assert "Spouse" in reason


def test_house_dependent_code_dc():
    pts, reason = score_spouse_dependent(_trade(owner="DC"))
    assert pts == POINTS_SPOUSE_DEPENDENT
    assert "Dependent" in reason


def test_house_joint_code_jt():
    pts, reason = score_spouse_dependent(_trade(owner="JT"))
    assert pts == POINTS_SPOUSE_DEPENDENT


# ─── Senate eFD full-word owner labels (the actual bug) ───

def test_senate_spouse_word_label():
    """Real Senate PTR reports render this as literal 'Spouse', confirmed live."""
    pts, reason = score_spouse_dependent(_trade(owner="Spouse"))
    assert pts == POINTS_SPOUSE_DEPENDENT
    assert "Spouse" in reason


def test_senate_child_word_label():
    """
    Real Senate PTR reports render this as literal 'Child' — NOT
    'Dependent' or 'Dependent Child'. This is the core regression: on
    unmodified main (and even under PR #3's guessed vocabulary), this
    case is silently missed and scores 0.
    """
    pts, reason = score_spouse_dependent(_trade(owner="Child"))
    assert pts == POINTS_SPOUSE_DEPENDENT
    assert "Dependent" in reason


def test_senate_joint_word_label():
    """Real Senate PTR reports render this as literal 'Joint', confirmed live."""
    pts, reason = score_spouse_dependent(_trade(owner="Joint"))
    assert pts == POINTS_SPOUSE_DEPENDENT


def test_senate_owner_label_case_and_whitespace_insensitive():
    pts, _ = score_spouse_dependent(_trade(owner="  child  "))
    assert pts == POINTS_SPOUSE_DEPENDENT


# ─── Legacy/alternate word forms should still be accepted ───

def test_dependent_child_word_form_still_works():
    pts, _ = score_spouse_dependent(_trade(owner="Dependent Child"))
    assert pts == POINTS_SPOUSE_DEPENDENT


def test_joint_tenants_word_form_still_works():
    pts, _ = score_spouse_dependent(_trade(owner="Joint Tenants"))
    assert pts == POINTS_SPOUSE_DEPENDENT


# ─── The member's own trades must NOT be flagged ───

def test_self_owner_no_signal():
    pts, reason = score_spouse_dependent(_trade(owner="Self"))
    assert pts == 0
    assert reason == ""


def test_blank_owner_no_signal():
    pts, reason = score_spouse_dependent(_trade(owner=""))
    assert pts == 0
    assert reason == ""


# ─── Fallback: description text still catches edge cases ───

def test_description_keyword_fallback_still_works():
    pts, _ = score_spouse_dependent(
        _trade(owner="", description="Trade made in a joint account")
    )
    assert pts == POINTS_SPOUSE_DEPENDENT


# ─── Real live-data fixtures (captured from actual Senate PTR reports) ───

REAL_SENATE_TRADES = [
    # Wyden — Berry Global/Amcor exchange (efdsearch.senate.gov UUID
    # 5ecc9b5c-07c1-4ec1-bd4a-2db759eff299), owner column literally "Spouse"
    _trade(owner="Spouse", asset="BERY - Berry Global Group, Inc. (Exchanged) Amcor plc Ordinary Shares (Received)"),
    # Fetterman-style report (UUID bb28c116-64b8-4088-a93d-8ba9965930ae),
    # both trades' owner column literally "Child"
    _trade(owner="Child", asset="Alphabet Inc. - Class C Capital Stock"),
    _trade(owner="Child", asset="HASBRO INC NOTE Rate/Coupon: 3.55% Matures: 11/19/2026"),
    # Boozman-style report (UUID db2a4c73-e714-4ad0-9548-b1b83f1d0773),
    # all 10 trades' owner column literally "Joint"
    _trade(owner="Joint", asset="Raytheon Technologies Corp"),
    _trade(owner="Joint", asset="Nvidia Corp"),
]


@pytest.mark.parametrize("trade", REAL_SENATE_TRADES)
def test_real_captured_senate_trades_are_flagged(trade):
    pts, reason = score_spouse_dependent(trade)
    assert pts == POINTS_SPOUSE_DEPENDENT, (
        f"Real Senate trade with owner={trade['owner']!r} was not flagged: {reason!r}"
    )


def test_score_trades_end_to_end_flags_senate_child_owner(tmp_path, monkeypatch):
    """
    End-to-end guard: score_trades() reads enriched_trades.json and must
    include the spouse/dependent reason text for a real Senate-shaped
    'Child'-owner trade, not just the unit-level score_spouse_dependent().
    """
    import json
    import scorer as scorer_module

    enriched_file = tmp_path / "enriched_trades.json"
    scored_file = tmp_path / "scored_trades.json"
    monkeypatch.setattr(scorer_module, "ENRICHED_TRADES_FILE", str(enriched_file))
    monkeypatch.setattr(scorer_module, "SCORED_TRADES_FILE", str(scored_file))
    monkeypatch.setattr(scorer_module, "DATA_DIR", str(tmp_path))

    enriched_file.write_text(json.dumps([
        {
            "owner": "Child",
            "description": "",
            "asset": "Alphabet Inc. - Class C Capital Stock",
            "representative": "Some Senator",
            "ticker": "GOOG",
            "committees": [],
            "sector": "",
            "amount": "$1,001 - $15,000",
            "transaction_type": "Purchase",
            "transaction_date": "05/15/2025",
            "notification_date": "05/20/2025",
        }
    ]))

    scored = score_trades()
    assert len(scored) == 1
    assert "Dependent" in scored[0]["reason"] or "Spouse" in scored[0]["reason"]
    assert scored[0]["score"] >= POINTS_SPOUSE_DEPENDENT
