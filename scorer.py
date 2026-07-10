# scorer.py — Suspicion scoring system for congressional trades
# Scores each trade 0–100 based on multiple signals and tags them.

import json
import os
import re
import requests
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

try:
    import yfinance as yf
except ImportError:
    yf = None

from config import (
    ENRICHED_TRADES_FILE, SCORED_TRADES_FILE, DATA_DIR,
    SCORE_HIGH_ALERT, SCORE_SUSPICIOUS, SCORE_NOTEWORTHY,
    POINTS_COMMITTEE_MATCH, POINTS_WAYS_AND_MEANS,
    POINTS_LARGE_TRADE_100K, POINTS_LARGE_TRADE_50K,
    POINTS_DELAY_NEAR_LIMIT, POINTS_DELAY_LATE,
    POINTS_CLUSTER_3_PLUS, POINTS_CLUSTER_2,
    POINTS_SPOUSE_DEPENDENT, POINTS_CONTRARIAN_BUY,
    CONTRARIAN_DROP_THRESHOLD, CONTRARIAN_LOOKBACK_DAYS,
    COMMITTEE_SECTOR_MAP,
    CONGRESS_API_BASE_URL, LEGISLATION_TIMING_LOOKBACK_DAYS,
    POINTS_LEGISLATION_TIMING,
)

load_dotenv()
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY", "")


# ─── SIGNAL 1: COMMITTEE/SECTOR MATCH ───

def score_committee_match(trade):
    """
    +25 if a member's committee relates to the stock's sector.
    +10 for Ways and Means (affects all sectors via tax policy).
    """
    committees = trade.get("committees", [])
    sector = trade.get("sector", "")
    if not committees or not sector:
        return 0, ""

    # Check Ways and Means first (special case)
    for comm in committees:
        if "Ways and Means" in comm:
            return POINTS_WAYS_AND_MEANS, f"Committee match: {comm} → {sector} (tax policy, +{POINTS_WAYS_AND_MEANS})"

    # Check specific committee-sector mappings
    for comm in committees:
        for keyword, sectors in COMMITTEE_SECTOR_MAP.items():
            if keyword.lower() in comm.lower() and sector in sectors:
                return POINTS_COMMITTEE_MATCH, f"Committee match: {comm} → {sector} (+{POINTS_COMMITTEE_MATCH})"

    return 0, ""


# ─── SIGNAL 2: LARGE TRADE SIZE ───

def parse_amount_upper(amount_str):
    """Extract the upper bound dollar amount from a range like '$50,001 - $100,000'."""
    if not amount_str:
        return 0
    amounts = re.findall(r"\$([\d,]+)", amount_str)
    if amounts:
        return int(amounts[-1].replace(",", ""))
    return 0


def score_trade_size(trade):
    """+15 if upper bound > $100K, +10 if > $50K."""
    upper = parse_amount_upper(trade.get("amount", ""))
    if upper > 100_000:
        return POINTS_LARGE_TRADE_100K, f"Trade size {trade['amount']} (+{POINTS_LARGE_TRADE_100K})"
    if upper > 50_000:
        return POINTS_LARGE_TRADE_50K, f"Trade size {trade['amount']} (+{POINTS_LARGE_TRADE_50K})"
    return 0, ""


# ─── SIGNAL 3: DISCLOSURE DELAY ───

def parse_date(date_str):
    """Parse a date string in MM/DD/YYYY or YYYY-MM-DD format."""
    if not date_str:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def score_disclosure_delay(trade):
    """+15 if disclosure delay is 38–45 days, +8 if 30–37 days."""
    tx_date = parse_date(trade.get("transaction_date", ""))
    disc_date = parse_date(trade.get("notification_date", ""))
    if not tx_date or not disc_date:
        return 0, ""

    delay = (disc_date - tx_date).days
    if delay < 0:
        return 0, ""

    if 38 <= delay <= 45:
        return POINTS_DELAY_NEAR_LIMIT, f"Disclosure delay: {delay} days (near 45-day limit, +{POINTS_DELAY_NEAR_LIMIT})"
    if 30 <= delay <= 37:
        return POINTS_DELAY_LATE, f"Disclosure delay: {delay} days (+{POINTS_DELAY_LATE})"

    return 0, ""


# ─── SIGNAL 4: MULTIPLE MEMBERS TRADING SAME STOCK ───

def score_cluster_trades(trades):
    """
    +20 if 3+ different members traded the same ticker.
    +15 if 2 different members traded the same ticker.
    Returns a dict: ticker → (points, list of member names).
    """
    ticker_members = defaultdict(set)
    for trade in trades:
        ticker = trade.get("ticker", "")
        if ticker:
            ticker_members[ticker].add(trade.get("representative", ""))

    results = {}
    for ticker, members in ticker_members.items():
        if len(members) >= 3:
            results[ticker] = (POINTS_CLUSTER_3_PLUS, list(members))
        elif len(members) >= 2:
            results[ticker] = (POINTS_CLUSTER_2, list(members))

    return results


# ─── SIGNAL 5: SPOUSE/DEPENDENT TRADES ───

def score_spouse_dependent(trade):
    """+10 if the trade was made by a spouse or dependent."""
    owner = trade.get("owner", "").upper()
    description = trade.get("description", "").lower()
    asset = trade.get("asset", "").lower()

    # Owner codes: SP = spouse, DC = dependent child, JT = joint
    spouse_owners = {"SP", "DC"}
    spouse_keywords = ["spouse", "dependent", "joint"]

    if owner in spouse_owners:
        label = "Spouse" if owner == "SP" else "Dependent"
        return POINTS_SPOUSE_DEPENDENT, f"{label} trade (owner: {owner}, +{POINTS_SPOUSE_DEPENDENT})"

    if owner == "JT" or any(kw in description for kw in spouse_keywords):
        return POINTS_SPOUSE_DEPENDENT, f"Joint/spouse trade (+{POINTS_SPOUSE_DEPENDENT})"

    return 0, ""


# ─── SIGNAL 6: TIMING VS LEGISLATION ───

_committee_meeting_cache = {}  # (chamber, from_date, to_date) → list of meeting dicts


def get_congress_number(date):
    """Compute the Congress number (e.g. 119) that covers a given date."""
    return (date.year - 1789) // 2 + 1


def _committees_overlap(name_a, name_b):
    """Loose match between two committee name strings (handles subcommittee naming)."""
    a, b = name_a.lower(), name_b.lower()
    return bool(a) and bool(b) and (a in b or b in a)


def fetch_committee_meetings(chamber, from_date, to_date):
    """
    Fetch committee meetings for a chamber within [from_date, to_date] from the
    congress.gov API, resolving each meeting's date and committee name(s).

    Requires CONGRESS_API_KEY (see .env.example) — returns [] if unset, on
    request failure, or on any parsing error, so the rest of the pipeline is
    unaffected when this optional feature isn't configured.
    """
    cache_key = (chamber, from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d"))
    if cache_key in _committee_meeting_cache:
        return _committee_meeting_cache[cache_key]

    meetings = []
    if not CONGRESS_API_KEY or chamber not in ("House", "Senate"):
        _committee_meeting_cache[cache_key] = meetings
        return meetings

    congress = get_congress_number(to_date)

    try:
        list_resp = requests.get(
            f"{CONGRESS_API_BASE_URL}/committee-meeting/{congress}/{chamber.lower()}",
            params={
                "api_key": CONGRESS_API_KEY,
                "format": "json",
                "limit": 250,
                "fromDateTime": from_date.strftime("%Y-%m-%dT00:00:00Z"),
                "toDateTime": to_date.strftime("%Y-%m-%dT23:59:59Z"),
            },
            timeout=15,
        )
        if list_resp.status_code != 200:
            print(f"  Congress.gov API returned {list_resp.status_code} for {chamber} meetings")
            _committee_meeting_cache[cache_key] = meetings
            return meetings

        for item in list_resp.json().get("committeeMeetings", []):
            detail_url = item.get("url", "")
            if not detail_url:
                continue
            try:
                detail_resp = requests.get(
                    detail_url,
                    params={"api_key": CONGRESS_API_KEY, "format": "json"},
                    timeout=10,
                )
                if detail_resp.status_code != 200:
                    continue

                meeting = detail_resp.json().get("committeeMeeting", {})
                raw_date = meeting.get("date", "")
                meeting_date = None
                if raw_date:
                    try:
                        meeting_date = datetime.strptime(raw_date[:10], "%Y-%m-%d")
                    except ValueError:
                        pass

                committee_names = [c.get("name", "") for c in meeting.get("committees", [])]
                meetings.append({
                    "date": meeting_date,
                    "title": meeting.get("title", ""),
                    "committees": committee_names,
                })
            except requests.RequestException:
                continue
    except requests.RequestException as e:
        print(f"  Congress.gov API request failed: {e}")

    _committee_meeting_cache[cache_key] = meetings
    return meetings


def score_legislation_timing(trade):
    """
    +20 if a committee the member sits on held a hearing/meeting within
    LEGISLATION_TIMING_LOOKBACK_DAYS of the trade date, and that committee
    maps (via COMMITTEE_SECTOR_MAP) to the stock's sector.

    Requires a free congress.gov API key set as CONGRESS_API_KEY in .env
    (see .env.example). Returns 0 with no error if it's not configured —
    the rest of the pipeline works without it.
    """
    if not CONGRESS_API_KEY:
        return 0, ""

    committees = trade.get("committees", [])
    sector = trade.get("sector", "")
    chamber = trade.get("chamber", "")
    tx_date = parse_date(trade.get("transaction_date", ""))

    if not committees or not sector or not tx_date or chamber not in ("House", "Senate"):
        return 0, ""

    window_start = tx_date - timedelta(days=LEGISLATION_TIMING_LOOKBACK_DAYS)
    window_end = tx_date + timedelta(days=LEGISLATION_TIMING_LOOKBACK_DAYS)

    try:
        meetings = fetch_committee_meetings(chamber, window_start, window_end)
    except Exception as e:
        print(f"  Legislation timing lookup failed: {e}")
        return 0, ""

    for meeting in meetings:
        meeting_date = meeting.get("date")
        if not meeting_date:
            continue
        days_apart = abs((meeting_date - tx_date).days)
        if days_apart > LEGISLATION_TIMING_LOOKBACK_DAYS:
            continue

        for meeting_comm in meeting.get("committees", []):
            if not any(_committees_overlap(mc, meeting_comm) for mc in committees):
                continue
            for keyword, sectors in COMMITTEE_SECTOR_MAP.items():
                if keyword.lower() in meeting_comm.lower() and sector in sectors:
                    return (
                        POINTS_LEGISLATION_TIMING,
                        f"Legislation timing: {meeting_comm} met {days_apart}d from trade "
                        f"date, sector {sector} (+{POINTS_LEGISLATION_TIMING})",
                    )

    return 0, ""


# ─── SIGNAL 7: CONTRARIAN BUY ───

def score_contrarian(trade):
    """
    +10 if the stock dropped >10% in the 30 days before a purchase.
    Suggests the member may have non-public information.
    """
    if yf is None:
        return 0, ""

    ticker = trade.get("ticker", "")
    tx_type = trade.get("transaction_type", "")
    tx_date = parse_date(trade.get("transaction_date", ""))

    # Only applies to purchases
    if not ticker or "Purchase" not in tx_type or not tx_date:
        return 0, ""

    try:
        start = tx_date - timedelta(days=CONTRARIAN_LOOKBACK_DAYS)
        end = tx_date - timedelta(days=1)
        stock = yf.Ticker(ticker)
        hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

        if hist.empty or len(hist) < 5:
            return 0, ""

        price_start = hist["Close"].iloc[0]
        price_end = hist["Close"].iloc[-1]
        pct_change = ((price_end - price_start) / price_start) * 100

        if pct_change < CONTRARIAN_DROP_THRESHOLD:
            return POINTS_CONTRARIAN_BUY, f"Contrarian buy: {ticker} down {abs(pct_change):.1f}% in prior 30 days (+{POINTS_CONTRARIAN_BUY})"

        # Include the price change info in reason even if no points
        return 0, f"{ticker} {pct_change:+.1f}% in prior 30 days (no signal)"

    except Exception as e:
        return 0, ""


# ─── MAIN SCORING ───

def tag_from_score(score):
    """Convert numeric score to a tag."""
    if score >= SCORE_HIGH_ALERT:
        return "high_alert"
    if score >= SCORE_SUSPICIOUS:
        return "suspicious"
    if score >= SCORE_NOTEWORTHY:
        return "noteworthy"
    return "routine"


def score_trades():
    """
    Load enriched trades, score each one, save results.
    """
    if not os.path.exists(ENRICHED_TRADES_FILE):
        print(f"No enriched trades found at {ENRICHED_TRADES_FILE}. Run enricher.py first.")
        return []

    with open(ENRICHED_TRADES_FILE, "r") as f:
        trades = json.load(f)

    print(f"Scoring {len(trades)} trade(s)...\n")

    # Pre-compute cluster signal (needs all trades at once)
    cluster_results = score_cluster_trades(trades)

    scored = []
    for trade in trades:
        total_score = 0
        reasons = []

        # Signal 1: Committee/sector match
        pts, reason = score_committee_match(trade)
        if pts:
            total_score += pts
            reasons.append(reason)

        # Signal 2: Trade size
        pts, reason = score_trade_size(trade)
        if pts:
            total_score += pts
            reasons.append(reason)

        # Signal 3: Disclosure delay
        pts, reason = score_disclosure_delay(trade)
        if pts:
            total_score += pts
            reasons.append(reason)

        # Signal 4: Cluster trading
        ticker = trade.get("ticker", "")
        if ticker in cluster_results:
            cluster_pts, cluster_members = cluster_results[ticker]
            other_members = [m for m in cluster_members if m != trade.get("representative")]
            if other_members:
                total_score += cluster_pts
                names = ", ".join(other_members)
                reasons.append(f"Multiple members traded {ticker}: {names} (+{cluster_pts})")

        # Signal 5: Spouse/dependent
        pts, reason = score_spouse_dependent(trade)
        if pts:
            total_score += pts
            reasons.append(reason)

        # Signal 6: Legislation timing (placeholder)
        pts, reason = score_legislation_timing(trade)
        if pts:
            total_score += pts
            reasons.append(reason)

        # Signal 7: Contrarian buy
        pts, reason = score_contrarian(trade)
        if pts:
            total_score += pts
            reasons.append(reason)

        # Cap at 100
        total_score = min(total_score, 100)
        tag = tag_from_score(total_score)

        # Build final reason string
        reason_str = " ".join(reasons)
        if reasons:
            reason_str += f" Total: {total_score} — {tag}."
        else:
            reason_str = f"No signals fired. Total: {total_score} — {tag}."

        trade["score"] = total_score
        trade["tag"] = tag
        trade["reason"] = reason_str
        scored.append(trade)

    # Sort by score descending
    scored.sort(key=lambda t: t["score"], reverse=True)

    # Save
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SCORED_TRADES_FILE, "w") as f:
        json.dump(scored, f, indent=2)

    print(f"Saved {len(scored)} scored trade(s) to {SCORED_TRADES_FILE}")
    return scored


# ─── RUN DIRECTLY FOR TESTING ───
if __name__ == "__main__":
    trades = score_trades()

    print("\n" + "=" * 70)
    print("SCORED TRADES (sorted by suspicion)")
    print("=" * 70)

    for t in trades:
        score = t["score"]
        tag = t["tag"].upper()

        # Color indicator
        if tag == "HIGH_ALERT":
            indicator = "!!!"
        elif tag == "SUSPICIOUS":
            indicator = "!! "
        elif tag == "NOTEWORTHY":
            indicator = "!  "
        else:
            indicator = "   "

        print(f"\n{indicator} [{score:3d}] {tag}")
        print(f"    Member:  {t['representative']}")
        print(f"    Asset:   {t['asset']} ({t['ticker'] or 'no ticker'})")
        print(f"    Type:    {t['transaction_type']}  |  Amount: {t['amount']}")
        print(f"    Date:    {t['transaction_date']}")
        print(f"    Reason:  {t['reason']}")
