# test_scorer.py — Regression tests for scorer.py's contrarian-buy signal
#
# Covers an off-by-one in score_contrarian()'s price-history window: pandas
# `.loc[start:end]` slicing is inclusive on both ends, so `end` must be
# `tx_date - 1 day` to include the most recent trading day *before* the
# purchase. Using `tx_date - 2 days` silently drops that day from the
# window, which can understate OR overstate the true pre-purchase price
# move enough to flip the contrarian-buy signal on real tickers (confirmed
# live against real yfinance history for NVDA/TSLA/META/AMD — dozens of
# real purchase dates flip across the -10% threshold purely from this
# one-day window shift).

import pandas as pd
from datetime import datetime

import scorer


def _history(dates, closes):
    return pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(dates))


def test_contrarian_includes_last_trading_day_before_purchase(monkeypatch):
    """
    tx_date is a Tuesday, so the trading day immediately before it (Monday)
    is a real business day, while tx_date - 2 (Sunday) is not. A sharp drop
    lands only on that Monday. The fix must include it; the pre-fix
    behavior silently excludes it and misses the signal entirely.
    """
    tx_date = datetime(2024, 3, 5)  # Tuesday

    dates = pd.bdate_range(end=datetime(2024, 3, 4), periods=30)  # ... through Mon Mar 4
    closes = [100.0] * (len(dates) - 1) + [85.0]  # -15% drop lands on the very last day (Mon Mar 4)
    hist = _history(dates, closes)

    monkeypatch.setattr(scorer, "fetch_price_history", lambda ticker: hist)

    trade = {
        "ticker": "TEST",
        "transaction_type": "Purchase",
        "transaction_date": tx_date.strftime("%m/%d/%Y"),
    }

    points, reason = scorer.score_contrarian(trade)

    assert points == scorer.POINTS_CONTRARIAN_BUY, (
        f"Expected the contrarian-buy signal to fire using the drop on the last "
        f"trading day before the purchase, got points={points} reason={reason!r}"
    )
    assert "down" in reason


def test_contrarian_excludes_the_purchase_date_itself(monkeypatch):
    """
    Sanity check in the other direction: a drop that only happens ON the
    purchase date itself (not before it) must NOT count toward the
    pre-purchase contrarian window.
    """
    tx_date = datetime(2024, 3, 5)  # Tuesday

    dates = pd.bdate_range(end=tx_date, periods=30)  # includes tx_date itself
    closes = [100.0] * (len(dates) - 1) + [50.0]  # huge drop only on tx_date
    hist = _history(dates, closes)

    monkeypatch.setattr(scorer, "fetch_price_history", lambda ticker: hist)

    trade = {
        "ticker": "TEST",
        "transaction_type": "Purchase",
        "transaction_date": tx_date.strftime("%m/%d/%Y"),
    }

    points, reason = scorer.score_contrarian(trade)

    assert points == 0, (
        f"The purchase-date price itself must not be included in the "
        f"pre-purchase window, got points={points} reason={reason!r}"
    )


def test_contrarian_no_signal_on_flat_prices(monkeypatch):
    """Non-regression: flat prices never fire the signal, regardless of window edges."""
    tx_date = datetime(2024, 3, 5)

    dates = pd.bdate_range(end=datetime(2024, 3, 4), periods=30)
    closes = [100.0] * len(dates)
    hist = _history(dates, closes)

    monkeypatch.setattr(scorer, "fetch_price_history", lambda ticker: hist)

    trade = {
        "ticker": "TEST",
        "transaction_type": "Purchase",
        "transaction_date": tx_date.strftime("%m/%d/%Y"),
    }

    points, reason = scorer.score_contrarian(trade)
    assert points == 0
