# config.py — Centralized configuration for the Congressional Trading Tracker
# Edit values here to customize the pipeline behavior.

import os

# ─── PROJECT PATHS ───
# All paths are relative to the project root directory.
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")

SEEN_TRADES_FILE = os.path.join(DATA_DIR, "seen_trades.json")
PARSED_TRADES_FILE = os.path.join(DATA_DIR, "parsed_trades.json")
ENRICHED_TRADES_FILE = os.path.join(DATA_DIR, "enriched_trades.json")
SCORED_TRADES_FILE = os.path.join(DATA_DIR, "scored_trades.json")
RUN_LOG_FILE = os.path.join(DATA_DIR, "run_log.txt")

# ─── DATA SOURCES ───
HOUSE_CLERK_URL = "https://disclosures-clerk.house.gov/FinancialDisclosure/ViewMemberSearchResult"
HOUSE_MEMBER_XML = "https://clerk.house.gov/xml/lists/MemberData.xml"
SENATE_EFDS_URL = "https://efdsearch.senate.gov"
SENATE_ASSIGNMENTS_URL = "https://www.senate.gov/general/committee_assignments/assignments.htm"

# ─── SCORING THRESHOLDS ───
# A trade's total score (0–100) determines its tag:
SCORE_HIGH_ALERT = 76    # score >= 76 → "high_alert"
SCORE_SUSPICIOUS = 51    # score >= 51 → "suspicious"
SCORE_NOTEWORTHY = 26    # score >= 26 → "noteworthy"
                          # score <  26 → "routine"

# ─── SCORING POINT VALUES ───
# Signal 1: Committee/sector match
POINTS_COMMITTEE_MATCH = 25
POINTS_WAYS_AND_MEANS = 10     # Ways & Means matches all sectors at reduced points

# Signal 2: Trade size
POINTS_LARGE_TRADE_100K = 15   # Upper bound > $100,000
POINTS_LARGE_TRADE_50K = 10    # Upper bound > $50,000

# Signal 3: Disclosure delay
POINTS_DELAY_NEAR_LIMIT = 15   # 38–45 days (near the 45-day legal deadline)
POINTS_DELAY_LATE = 8          # 30–37 days

# Signal 4: Cluster trading (multiple members on same ticker)
POINTS_CLUSTER_3_PLUS = 20     # 3+ different members
POINTS_CLUSTER_2 = 15          # 2 different members

# Signal 5: Spouse/dependent trade
POINTS_SPOUSE_DEPENDENT = 10

# Signal 6: Legislation timing (placeholder — not yet implemented)
POINTS_LEGISLATION_TIMING = 20

# Signal 7: Contrarian buy (stock dropped >10% before purchase)
POINTS_CONTRARIAN_BUY = 10
CONTRARIAN_DROP_THRESHOLD = -10  # percent change threshold
CONTRARIAN_LOOKBACK_DAYS = 35    # days of price history to check

# ─── COMMITTEE → SECTOR MAPPINGS ───
# Maps committee name keywords to stock sectors they oversee.
# NOTE: these sector names must match yfinance's `info["sector"]` taxonomy
# exactly (it does NOT use GICS names like "Information Technology" or
# "Consumer Discretionary" — see e.g. AAPL -> "Technology",
# AMZN -> "Consumer Cyclical", WMT -> "Consumer Defensive",
# LIN -> "Basic Materials"). Using the GICS names here silently breaks the
# committee/sector match signal since `sector in sectors` never matches.
COMMITTEE_SECTOR_MAP = {
    "Energy and Commerce": [
        "Energy", "Healthcare", "Communication Services", "Consumer Cyclical",
    ],
    "Financial Services": ["Financial Services", "Real Estate"],
    "Armed Services": ["Industrials"],
    "Agriculture": ["Consumer Defensive", "Basic Materials"],
    "Science": ["Technology"],
    "Technology": ["Technology"],
    "Transportation": ["Industrials", "Energy"],
}

# ─── EMAIL SETTINGS ───
# Tiers displayed in the email report: (tag, display_label, header_color, row_background)
EMAIL_TIERS = [
    ("high_alert", "High Alert", "#dc2626", "#fef2f2"),
    ("suspicious", "Suspicious", "#d97706", "#fffbeb"),
    ("noteworthy", "Noteworthy", "#2563eb", "#eff6ff"),
]

# Only trades scoring above this threshold appear in the email.
# Trades at or below this score are tagged "routine" and omitted.
EMAIL_MIN_SCORE = 25

# SMTP server settings (Gmail default)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
