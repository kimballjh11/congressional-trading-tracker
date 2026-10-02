# test_emailer.py — regression tests for HTML-escaping of trade data in emails
#
# emailer.build_trade_row() interpolates several fields sourced from
# scraped/parsed government PDFs and HTML pages (representative name,
# asset name, ticker, committee names, free-text "reason", pdf_url, and a
# transaction-type fallback) directly into an HTML f-string. None of this
# data is operator-controlled, so a stray "&"/"<"/">"/'"' picked up from a
# filing can corrupt the rendered email or have an email client interpret
# injected markup/attributes literally. These tests prove every one of
# those fields is HTML-escaped before it reaches the output.

import emailer


def _trade(**overrides):
    base = {
        "representative": "Rep. Jane Doe",
        "asset": "Example Corp. Common Stock",
        "ticker": "EX",
        "transaction_type": "Purchase",
        "committees": ["Financial Services"],
        "amount": "$1,001 - $15,000",
        "transaction_date": "01/01/2026",
        "notification_date": "01/15/2026",
        "score": 40,
        "reason": "Example reason",
        "pdf_url": "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/1.pdf",
    }
    base.update(overrides)
    return base


def test_representative_name_is_escaped():
    row = emailer.build_trade_row(_trade(representative="O'Brien <script>alert(1)</script>"))
    assert "<script>" not in row
    assert "&lt;script&gt;" in row


def test_asset_name_ampersand_is_escaped():
    # AT&T is a real, extremely common holding — a bare "&" must not be
    # allowed through unescaped.
    row = emailer.build_trade_row(_trade(asset="AT&T Inc. Common Stock (T)"))
    assert "AT&T Inc." not in row
    assert "AT&amp;T Inc." in row


def test_ticker_is_escaped():
    row = emailer.build_trade_row(_trade(ticker="<b>EVIL</b>"))
    assert "<b>EVIL</b>" not in row
    assert "&lt;b&gt;EVIL&lt;/b&gt;" in row


def test_committees_are_escaped():
    row = emailer.build_trade_row(_trade(committees=["<img src=x onerror=alert(1)>"]))
    assert "<img src=x onerror=alert(1)>" not in row
    assert "&lt;img src=x onerror=alert(1)&gt;" in row


def test_amount_and_transaction_date_are_escaped():
    row = emailer.build_trade_row(_trade(amount="<b>$1</b>", transaction_date="<i>01/01/2026</i>"))
    assert "<b>$1</b>" not in row
    assert "<i>01/01/2026</i>" not in row


def test_reason_is_escaped():
    row = emailer.build_trade_row(_trade(reason="<img src=x onerror=alert(1)>"))
    assert "<img src=x onerror=alert(1)>" not in row
    assert "&lt;img src=x onerror=alert(1)&gt;" in row


def test_pdf_url_cannot_break_out_of_href_attribute():
    malicious_url = 'https://example.com/f.pdf" onmouseover="alert(1)'
    row = emailer.build_trade_row(_trade(pdf_url=malicious_url))
    assert 'onmouseover="alert(1)' not in row
    assert "&quot;" in row
    # The link itself should still render using the (now attribute-safe) URL.
    assert '<a href="https://example.com/f.pdf&quot; onmouseover=&quot;alert(1)"' in row


def test_transaction_type_fallback_is_escaped():
    # When a trade's transaction_type is neither "Purchase" nor "Sale"
    # (e.g. a malformed Senate HTML cell), the raw value is used as the
    # displayed type label directly — this fallback path must also escape.
    row = emailer.build_trade_row(_trade(transaction_type="<b>Exchange</b>"))
    assert "<b>Exchange</b>" not in row
    assert "&lt;b&gt;Exchange&lt;/b&gt;" in row


def test_normal_trade_still_renders_readable_text():
    # Regression guard: ordinary, non-malicious data should render exactly
    # as before (plain readable text, not literal escaped entities).
    row = emailer.build_trade_row(_trade())
    assert "Rep. Jane Doe" in row
    assert "Example Corp. Common Stock" in row
    assert "<strong>EX</strong>" in row
    assert "Financial Services" in row
    assert "BUY" in row
    assert 'href="https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/1.pdf"' in row


def test_purchase_and_sale_labels_unaffected():
    buy_row = emailer.build_trade_row(_trade(transaction_type="Purchase"))
    assert "BUY" in buy_row

    sale_row = emailer.build_trade_row(_trade(transaction_type="Sale (full)"))
    assert "SELL" in sale_row

    partial_row = emailer.build_trade_row(_trade(transaction_type="Sale (partial)"))
    assert "SELL (partial)" in partial_row
