# test_scorer.py — tests for the CONTRARIAN_LOOKBACK_DAYS / score_contrarian() mismatch fix.
#
# Bug: config.CONTRARIAN_LOOKBACK_DAYS was 35, but score_contrarian()'s own docstring,
# its printed "reason" text ("... in prior 30 days ..."), and README.md's scoring table
# all say the lookback window is 30 days. The real 35-day window pulls in 5 extra days
# of price history that can flip whether the >10% drop threshold is crossed, producing
# a contrarian-buy signal (and matching email copy) for a window the tool never actually
# claims to use.
#
# Live-confirmed 2026-10-03 via real yfinance data: a trade in META or AMD around
# 2026-08-26 triggers the "Contrarian buy" signal under the old 35-day window
# (-12.32% / -14.32%) but would NOT trigger it under the documented 30-day window
# (-7.4% / -4.38%) -- i.e. a real false-positive suspicion signal caused purely by the
# lookback-days mismatch. These tests use deterministic synthetic price data (not a
# live network call) so they are fast and reproducible, but they reproduce the exact
# same "old price_start pulled from outside the documented window" shape as that live
# finding.

import pandas as pd
import pytest

import config
import scorer


def _trade(ticker="ACME", tx_date="2026-09-15", tx_type="Purchase"):
    return {
        "ticker": ticker,
        "transaction_type": tx_type,
        "transaction_date": tx_date,
    }


def _make_history():
    """
    Build a synthetic daily Close-price series spanning 2026-08-11 through 2026-09-13.

    - 2026-08-11 through 2026-08-15 (i.e. only reachable by a 35-day-or-wider window
      measured from the 2026-09-15 purchase date below): price is high (150).
    - 2026-08-16 onward (reachable by the documented 30-day window): price is a flat
      105, dropping to 100 only on the very last day.

    A 30-day lookback (start = 2026-08-16) sees price_start=105 -> price_end=100,
    a -4.8% change: no contrarian signal, matching the documented behavior.
    A 35-day lookback (start = 2026-08-11) sees price_start=150 -> price_end=100,
    a -33.3% change: a (bogus, undocumented) contrarian signal.
    """
    idx = pd.bdate_range("2026-08-11", "2026-09-13")
    closes = []
    for d in idx:
        if d < pd.Timestamp("2026-08-16"):
            closes.append(150.0)
        elif d == idx[-1]:
            closes.append(100.0)
        else:
            closes.append(105.0)
    return pd.DataFrame({"Close": closes}, index=idx)


@pytest.fixture
def fake_history(monkeypatch):
    hist = _make_history()
    monkeypatch.setattr(scorer, "fetch_price_history", lambda ticker: hist)
    return hist


def test_lookback_days_matches_documented_30_day_window():
    """
    config.CONTRARIAN_LOOKBACK_DAYS must match the "30 days" wording baked into
    score_contrarian()'s own docstring, its printed reason text, and README.md's
    scoring table -- not some other value that silently widens the real window.
    """
    assert config.CONTRARIAN_LOOKBACK_DAYS == 30
    assert "30 days" in scorer.score_contrarian.__doc__


def test_documented_30_day_window_does_not_flag_contrarian(fake_history):
    score, reason = scorer.score_contrarian(_trade())
    assert score == 0
    assert "no signal" in reason


def test_old_35_day_window_would_have_falsely_flagged_contrarian(monkeypatch, fake_history):
    """
    Regression guard: if CONTRARIAN_LOOKBACK_DAYS ever regresses back to 35 (or
    anything wider than what the docstring/README promise), this same synthetic
    history would wrongly earn the +10 contrarian-buy signal.
    """
    monkeypatch.setattr(scorer, "CONTRARIAN_LOOKBACK_DAYS", 35)
    score, reason = scorer.score_contrarian(_trade())
    assert score == config.POINTS_CONTRARIAN_BUY
    assert "Contrarian buy" in reason


def test_contrarian_zero_price_start_does_not_raise(monkeypatch):
    """
    A zero (or otherwise falsy) price_start -- e.g. a delisted/halted ticker with a
    reported $0 close -- must not raise ZeroDivisionError out of score_contrarian();
    it should just report no signal like any other unusable price history.
    """
    idx = pd.bdate_range("2026-08-16", "2026-09-13")
    closes = [0.0] + [100.0] * (len(idx) - 1)
    hist = pd.DataFrame({"Close": closes}, index=idx)
    monkeypatch.setattr(scorer, "fetch_price_history", lambda ticker: hist)

    score, reason = scorer.score_contrarian(_trade())
    assert score == 0
    assert reason == ""


def test_non_purchase_trade_never_calls_price_history(monkeypatch):
    called = []
    monkeypatch.setattr(scorer, "fetch_price_history", lambda ticker: called.append(ticker))
    score, reason = scorer.score_contrarian(_trade(tx_type="Sale (Full)"))
    assert score == 0
    assert reason == ""
    assert called == []
