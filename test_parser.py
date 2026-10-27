# test_parser.py — tests for parser.py's per-filing fetch-failure handling
#
# Context: download_pdf()/parse_house_filing()/parse_senate_filing() used to
# silently return None/[] when a filing's report failed to download (network
# error, non-200 status, bot-detection block, etc). That made a transient
# fetch failure look EXACTLY like a filing that genuinely had zero trades,
# so parse_all_filings() had no way to tell main.py which filings were
# actually processed. main.py then called mark_filings_seen(all_filings)
# with every filing the scrapers found, permanently marking failed-download
# filings as "seen" even though their trades were never fetched — losing
# them forever with no retry. This is a live, real-world scenario: Senate
# EFDS's Akamai bot protection has 403'd individual report-view pages in
# real production runs while the search step itself still succeeded.
#
# The fix: fetch/parse failures now raise FilingFetchError, parse_all_filings()
# catches it per-filing (so one bad filing doesn't lose the whole batch) and
# returns (all_trades, successful_filing_ids) — only filings that actually
# succeeded appear in successful_filing_ids, which is what callers must use
# to decide what's safe to mark "seen".

from unittest.mock import patch, MagicMock

import pytest

import parser as parser_module


def test_download_pdf_raises_on_non_200():
    fake_response = MagicMock(status_code=403)
    with patch.object(parser_module.requests, "get", return_value=fake_response):
        with pytest.raises(parser_module.FilingFetchError):
            parser_module.download_pdf("https://example.com/x.pdf")


def test_parse_senate_filing_raises_on_non_200():
    fake_response = MagicMock(status_code=403, text="Access Denied")
    filing = {"filing_id": "senate_abc", "pdf_url": "https://efdsearch.senate.gov/x"}
    with patch.object(parser_module.requests, "get", return_value=fake_response):
        with pytest.raises(parser_module.FilingFetchError):
            parser_module.parse_senate_filing(filing)


def test_parse_house_filing_raises_when_no_text_extracted():
    filing = {"filing_id": "house_123", "pdf_url": "https://x/a.pdf", "representative": "A"}
    with patch.object(parser_module, "download_pdf", return_value=b"fake-pdf-bytes"):
        with patch.object(parser_module, "extract_text_from_pdf", return_value=""):
            with pytest.raises(parser_module.FilingFetchError):
                parser_module.parse_house_filing(filing)


def test_parse_all_filings_excludes_failed_filing_from_successful_ids(tmp_path, monkeypatch):
    """
    The core regression test: a filing whose download fails must NOT appear
    in successful_filing_ids, even though parsing overall completes and
    other filings' trades are returned normally.
    """
    monkeypatch.setattr(parser_module, "PARSED_TRADES_FILE", str(tmp_path / "parsed.json"))
    monkeypatch.setattr(parser_module, "DATA_DIR", str(tmp_path))

    filings = [
        {"filing_id": "house_111", "chamber": "House", "representative": "A", "pdf_url": "https://x/a.pdf"},
        {"filing_id": "senate_222", "chamber": "Senate", "representative": "B", "pdf_url": "https://x/b"},
    ]

    def fake_parse_filing(filing):
        if filing["filing_id"] == "senate_222":
            raise parser_module.FilingFetchError("Failed to download Senate report: 403")
        return [{"ticker": "FOO", "representative": "A"}]

    with patch.object(parser_module, "parse_filing", side_effect=fake_parse_filing):
        trades, successful_ids = parser_module.parse_all_filings(filings)

    assert trades == [{"ticker": "FOO", "representative": "A"}]
    assert successful_ids == ["house_111"]
    assert "senate_222" not in successful_ids


def test_parse_all_filings_one_failure_does_not_lose_other_filings_trades(tmp_path, monkeypatch):
    """A single filing raising FilingFetchError must not crash/empty the whole batch."""
    monkeypatch.setattr(parser_module, "PARSED_TRADES_FILE", str(tmp_path / "parsed.json"))
    monkeypatch.setattr(parser_module, "DATA_DIR", str(tmp_path))

    filings = [
        {"filing_id": "a", "pdf_url": "https://x/a"},
        {"filing_id": "b", "pdf_url": "https://x/b"},
        {"filing_id": "c", "pdf_url": "https://x/c"},
    ]

    def fake_parse_filing(filing):
        if filing["filing_id"] == "b":
            raise parser_module.FilingFetchError("boom")
        return [{"ticker": filing["filing_id"]}]

    with patch.object(parser_module, "parse_filing", side_effect=fake_parse_filing):
        trades, successful_ids = parser_module.parse_all_filings(filings)

    assert trades == [{"ticker": "a"}, {"ticker": "c"}]
    assert successful_ids == ["a", "c"]
