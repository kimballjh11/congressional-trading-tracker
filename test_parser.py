# test_parser.py — Tests for parser.py's per-filing error isolation
#
# Covers the bug fixed here: a single malformed/corrupted filing (server
# returns HTTP 200 but a non-PDF body — a bot-detection interstitial, a
# maintenance page, or a genuinely corrupted archived PDF) must not crash
# parse_all_filings() and silently discard every OTHER filing's
# already-extracted trades in the same run.

import json
from unittest.mock import MagicMock, patch

import pytest

import parser as parser_module

CORRUPT_NON_PDF_BODY = b"<html><body>Service Temporarily Unavailable</body></html>"


def _filing(filing_id, url, chamber="House"):
    return {
        "representative": f"Member {filing_id}",
        "state_district": "ZZ01",
        "filing_id": filing_id,
        "pdf_url": url,
        "chamber": chamber,
    }


def _patch_pipeline(monkeypatch, tmp_path):
    """Route parse_all_filings()'s output to an isolated tmp file, and make
    extract_text_from_pdf / parse_trades_from_text deterministic so tests
    focus on crash-isolation, not the real PDF/regex parsing (covered by
    other test files)."""
    parsed_file = tmp_path / "parsed_trades.json"
    monkeypatch.setattr(parser_module, "PARSED_TRADES_FILE", str(parsed_file))
    monkeypatch.setattr(parser_module, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(parser_module, "extract_text_from_pdf", lambda pdf_bytes: "some text")
    monkeypatch.setattr(
        parser_module, "parse_trades_from_text",
        lambda text: [{"asset": "Fake Asset", "ticker": "FAKE"}],
    )
    return parsed_file


def test_real_corrupted_pdf_body_does_not_crash_the_batch(monkeypatch, tmp_path):
    """The exact real-world trigger: the server returns HTTP 200 with a
    non-PDF body (bot-detection interstitial / corrupted archive / maintenance
    page). This is NOT a non-200 status, so a status-code-only check
    (FilingFetchError) never catches it — pdfplumber itself raises while
    extracting text. A single such filing, sandwiched between two good ones,
    must not wipe out the good ones' already-parsed trades."""
    parsed_file = tmp_path / "parsed_trades.json"
    monkeypatch.setattr(parser_module, "PARSED_TRADES_FILE", str(parsed_file))
    monkeypatch.setattr(parser_module, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        parser_module, "parse_trades_from_text",
        lambda text: [{"asset": "Fake Asset", "ticker": "FAKE"}],
    )

    good_url_1 = "https://example.test/good1.pdf"
    bad_url = "https://example.test/corrupt.pdf"
    good_url_2 = "https://example.test/good2.pdf"

    # A minimal but genuinely valid single-page PDF with extractable text,
    # generated once via pdfplumber's own writer-compatible structure isn't
    # needed here — extract_text_from_pdf is exercised for real against the
    # corrupt body, and against a body simple enough that pdfplumber accepts
    # it without raising (even if it extracts no text) for the good filings.
    minimal_ok_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n"
    )

    call_log = []

    def fake_get(url, *args, **kwargs):
        call_log.append(url)
        resp = MagicMock()
        resp.status_code = 200
        if url == bad_url:
            resp.content = CORRUPT_NON_PDF_BODY
        else:
            resp.content = minimal_ok_pdf
        return resp

    filings = [
        _filing("house_1", good_url_1),
        _filing("house_2", bad_url),
        _filing("house_3", good_url_2),
    ]

    with patch.object(parser_module.requests, "get", side_effect=fake_get):
        # Must not raise — the whole point of the fix.
        trades = parser_module.parse_all_filings(filings)

    # All 3 filings must have been attempted — the crash on filing 2 must not
    # abort processing of filing 3.
    assert call_log == [good_url_1, bad_url, good_url_2]

    # extract_text_from_pdf on the minimal PDF extracts no real text (no
    # content stream), so parse_trades_from_text is never reached for the
    # good filings either — that's fine, this test only asserts the batch
    # didn't crash and got to process every filing. See the dedicated test
    # below for trade-preservation with a controlled extract_text_from_pdf.
    assert isinstance(trades, list)
    assert parsed_file.exists()


def test_one_bad_filing_does_not_lose_other_filings_trades(monkeypatch, tmp_path):
    """Core regression: any exception while parsing one filing (network glitch,
    unexpected parsing bug, etc.) must not discard trades already extracted
    from other filings in the same batch."""
    parsed_file = _patch_pipeline(monkeypatch, tmp_path)

    good_url_1 = "https://example.test/good1.pdf"
    bad_url = "https://example.test/bad.pdf"
    good_url_2 = "https://example.test/good2.pdf"

    filings = [
        _filing("house_1", good_url_1),
        _filing("house_2", bad_url),
        _filing("house_3", good_url_2),
    ]

    call_log = []

    def fake_get(url, *args, **kwargs):
        call_log.append(url)
        if url == bad_url:
            raise ValueError("simulated unexpected parsing failure")
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"%PDF-1.4 fake bytes"
        return resp

    with patch.object(parser_module.requests, "get", side_effect=fake_get):
        trades = parser_module.parse_all_filings(filings)

    # All 3 filings attempted — filing 3 must not be skipped just because
    # filing 2 failed.
    assert call_log == [good_url_1, bad_url, good_url_2]

    # The two good filings' trades survive despite the bad filing between them.
    assert len(trades) == 2
    assert {t["filing_id"] for t in trades} == {"house_1", "house_3"}

    with open(parsed_file) as f:
        saved = json.load(f)
    assert len(saved) == 2


def test_all_filings_good_still_works_normally(monkeypatch, tmp_path):
    """Regression guard: normal, fully-successful batches are unaffected."""
    parsed_file = _patch_pipeline(monkeypatch, tmp_path)

    urls = ["https://example.test/a.pdf", "https://example.test/b.pdf"]
    filings = [_filing("house_a", urls[0]), _filing("house_b", urls[1])]

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"%PDF-1.4 fake bytes"
        return resp

    with patch.object(parser_module.requests, "get", side_effect=fake_get):
        trades = parser_module.parse_all_filings(filings)

    assert len(trades) == 2
    assert {t["filing_id"] for t in trades} == {"house_a", "house_b"}


def test_error_in_senate_filing_is_also_isolated(monkeypatch, tmp_path):
    """The fix must cover Senate (HTML) filings too, not just House PDFs —
    parse_filing() routes to parse_senate_filing() for chamber == 'Senate'."""
    parsed_file = _patch_pipeline(monkeypatch, tmp_path)

    good_house_url = "https://example.test/good.pdf"
    bad_senate_url = "https://example.test/senate_report/"

    def fake_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"%PDF-1.4 fake bytes"
        resp.text = "<html>unused</html>"
        return resp

    def raising_parse_senate_html(html, filing):
        raise RuntimeError("simulated Senate HTML parsing failure")

    monkeypatch.setattr(parser_module, "parse_senate_html", raising_parse_senate_html)

    filings = [
        _filing("house_good", good_house_url, chamber="House"),
        _filing("senate_bad", bad_senate_url, chamber="Senate"),
    ]

    with patch.object(parser_module.requests, "get", side_effect=fake_get):
        trades = parser_module.parse_all_filings(filings)

    assert len(trades) == 1
    assert trades[0]["filing_id"] == "house_good"


def test_error_message_names_the_failing_filing(monkeypatch, tmp_path, capsys):
    """The skipped filing should be clearly identifiable in the logs so it's
    not a silent failure — just a non-fatal one."""
    _patch_pipeline(monkeypatch, tmp_path)

    bad_url = "https://example.test/bad.pdf"
    filings = [_filing("house_distinctive_id_123", bad_url)]

    def fake_get(url, *args, **kwargs):
        raise ValueError("boom")

    with patch.object(parser_module.requests, "get", side_effect=fake_get):
        trades = parser_module.parse_all_filings(filings)

    assert trades == []
    captured = capsys.readouterr()
    assert "house_distinctive_id_123" in captured.out


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
