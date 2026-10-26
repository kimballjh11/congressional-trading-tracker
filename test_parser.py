# test_parser.py — Tests for parser.py
# Each fixture below is captured verbatim (pdfplumber text extraction output)
# from a real, live House PTR filing, to reproduce real-world parsing bugs.

from parser import parse_trades_from_text, parse_single_trade


# From house_20033759 (Rouzer, David) — a self-owned (no owner code) trade
# whose "Filing Status" is "Amended". The PDF's "ID" column renders a numeric
# transaction-reference ID directly in front of the asset name.
ROUZER_AMENDED_SELF_OWNED = """Filing ID #20033759
Name: Hon. David Rouzer
State/District: NC07
ID Owner Asset Transaction Date Notification Amount Cap.
Type Date Gains >
$200?
2000152831 Boeing Company (BA) [ST] S 12/09/2025 12/09/2025 $1,001 - $15,000
F      S     : Amended
S          O : Interactive Brokers LLC
* For the complete list of asset type abbreviations, please visit https://fd.house.gov/reference/asset-type-codes.aspx.
"""

# From house_20033780 (Donalds, Byron) — a Spouse-owned ("SP") trade that is
# also Amended. The numeric ID precedes the "SP" owner code, so a naive
# owner-code match anchored at the start of the block misses it entirely.
DONALDS_AMENDED_SPOUSE_OWNED = """Filing ID #20033780
Name: Hon. Byron Donalds
State/District: FL19
ID Owner Asset Transaction Date Notification Amount Cap.
Type Date Gains >
$200?
2000152815 SP Bitcoin (CRYPTO:BTC) [CT] P 12/18/2025 12/18/2025 $50,001 -
$100,000
F      S     : Amended
* For the complete list of asset type abbreviations, please visit https://fd.house.gov/reference/asset-type-codes.aspx.
"""

# From house_20034201 (Alford, Mark) — an ordinary "New" (non-amended) trade
# with no leading transaction ID, used as a regression check.
ALFORD_NEW_SELF_OWNED = """Filing ID #20034201
Name: Hon. Mark Alford
State/District: MO04
ID Owner Asset Transaction Date Notification Amount Cap.
Type Date Gains >
$200?
Amazon.com, Inc. - Common Stock S (partial) 03/16/2026 03/16/2026 $1,001 - $15,000
(AMZN) [ST]
F      S     : New
S          O : Putnam Investments
"""


def test_amended_self_owned_trade_strips_leading_transaction_id():
    trades = parse_trades_from_text(ROUZER_AMENDED_SELF_OWNED)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["asset"] == "Boeing Company (BA)"
    assert "2000152831" not in trade["asset"]
    assert trade["owner"] == ""
    assert trade["ticker"] == "BA"
    assert trade["transaction_type"] == "Sale"


def test_amended_spouse_trade_recovers_owner_code_and_clean_asset():
    trades = parse_trades_from_text(DONALDS_AMENDED_SPOUSE_OWNED)
    assert len(trades) == 1
    trade = trades[0]
    # Before the fix, the leading numeric ID blocked the "SP" owner-code
    # match, so this trade's owner was wrongly blank and "2000152815 SP"
    # leaked straight into the asset name.
    assert trade["owner"] == "SP"
    assert trade["asset"] == "Bitcoin (CRYPTO:BTC)"
    assert "2000152815" not in trade["asset"]
    assert "SP" not in trade["asset"]
    assert trade["transaction_type"] == "Purchase"


def test_new_trade_without_leading_id_is_unaffected():
    trades = parse_trades_from_text(ALFORD_NEW_SELF_OWNED)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["asset"] == "Amazon.com, Inc. - Common Stock"
    assert trade["owner"] == ""
    assert trade["ticker"] == "AMZN"
    assert trade["transaction_type"] == "Sale (partial)"


def test_parse_single_trade_does_not_strip_short_leading_digits():
    # Guard against over-matching: a short digit prefix (e.g. part of a
    # legitimate asset name) should NOT be stripped — only a 6+ digit
    # transaction-reference ID is.
    block = "3M Company Common Stock P 01/01/2026 01/05/2026 $1,001 - $15,000"
    trade = parse_single_trade(block)
    assert trade["asset"].startswith("3M Company")
