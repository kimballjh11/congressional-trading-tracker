# test_seen_store.py — Regression tests for a real, live-reproduced data-loss
# bug: filings used to be marked "seen" the moment they were discovered in a
# search-results listing, BEFORE they were ever downloaded/parsed.
#
# Repro (see main.py's original flow, pre-fix):
#   1. scraper.get_new_trades() fetches the House Clerk's filing list and
#      immediately calls save_seen_trades() for every filing it finds.
#   2. parser.parse_all_filings() then tries to download each filing's PDF.
#      A transient failure (network blip, non-200 status) makes
#      download_pdf() return None, and parse_house_filing() silently
#      returns [] — no exception, no error surfaced to main.py.
#   3. Because step 1 already wrote that filing_id into seen_trades.json,
#      it is now permanently gone: it will never be scraped or retried
#      again, and its trades never appear in any report.
#
# The fix moves "seen" bookkeeping out of the scrapers entirely (see
# seen_store.py) and only marks a filing as seen in main.py, after
# parser.parse_all_filings() confirms it was actually fetched and parsed
# (parser.FilingFetchError is used to signal a retryable transient
# failure, which is excluded from the successful-filing-id list).

import json
from unittest.mock import MagicMock, patch

import pytest

import seen_store
import scraper
import senate_scraper
import parser as parser_module
import main as main_module


@pytest.fixture
def isolated_seen_file(tmp_path, monkeypatch):
    seen_file = tmp_path / "seen_trades.json"
    monkeypatch.setattr(seen_store, "SEEN_TRADES_FILE", str(seen_file))
    monkeypatch.setattr(seen_store, "DATA_DIR", str(tmp_path))
    return seen_file


# ─── seen_store.py itself ───

def test_load_seen_trades_missing_file_returns_empty_set(isolated_seen_file):
    assert seen_store.load_seen_trades() == set()


def test_save_and_load_round_trip(isolated_seen_file):
    seen_store.save_seen_trades({"house_1", "senate_2"})
    assert seen_store.load_seen_trades() == {"house_1", "senate_2"}


def test_mark_seen_adds_to_existing_set(isolated_seen_file):
    seen_store.save_seen_trades({"house_1"})
    seen_store.mark_seen(["house_2", "house_3"])
    assert seen_store.load_seen_trades() == {"house_1", "house_2", "house_3"}


def test_mark_seen_empty_list_is_noop_and_does_not_create_file(isolated_seen_file):
    seen_store.mark_seen([])
    assert not isolated_seen_file.exists()


# ─── scraper.py / senate_scraper.py must NOT persist on discovery ───

def test_get_new_trades_does_not_mark_anything_seen(isolated_seen_file, monkeypatch):
    """
    Regression guard for the core bug: merely discovering a filing in the
    House Clerk listing must not write it to seen_trades.json. Only a
    successful parse (via main.py -> seen_store.mark_seen) may do that.
    """
    fake_filings = [
        {"filing_id": "house_11111111", "representative": "A", "pdf_url": "u1"},
        {"filing_id": "house_22222222", "representative": "B", "pdf_url": "u2"},
    ]
    monkeypatch.setattr(scraper, "fetch_house_filings", lambda: fake_filings)

    new_trades = scraper.get_new_trades()

    assert [f["filing_id"] for f in new_trades] == ["house_11111111", "house_22222222"]
    assert not isolated_seen_file.exists()
    assert seen_store.load_seen_trades() == set()


def test_get_new_senate_trades_does_not_mark_anything_seen(isolated_seen_file, monkeypatch):
    fake_filings = [
        {"filing_id": "senate_abc", "representative": "C", "pdf_url": "u3"},
    ]
    monkeypatch.setattr(senate_scraper, "create_session", lambda: MagicMock())
    monkeypatch.setattr(senate_scraper, "search_ptr_filings", lambda session: fake_filings)

    new_trades = senate_scraper.get_new_senate_trades()

    assert [f["filing_id"] for f in new_trades] == ["senate_abc"]
    assert not isolated_seen_file.exists()


# ─── parser.py: a transient download failure must be retryable, not fatal ───

def _fake_pdf_filing(filing_id, pdf_url):
    return {
        "filing_id": filing_id,
        "representative": "Test Member",
        "state_district": "AA01",
        "pdf_url": pdf_url,
        "chamber": "House",
    }


def test_parse_all_filings_skips_failed_download_but_keeps_successful_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(parser_module, "PARSED_TRADES_FILE", str(tmp_path / "parsed_trades.json"))
    monkeypatch.setattr(parser_module, "DATA_DIR", str(tmp_path))

    good = _fake_pdf_filing("house_11111111", "https://example.com/good.pdf")
    bad = _fake_pdf_filing("house_22222222", "https://example.com/bad.pdf")

    def fake_parse_filing(filing):
        if filing["filing_id"] == "house_22222222":
            raise parser_module.FilingFetchError("simulated transient download failure")
        return [{"asset": "Apple Inc", "filing_id": filing["filing_id"]}]

    monkeypatch.setattr(parser_module, "parse_filing", fake_parse_filing)

    trades, successful_ids = parser_module.parse_all_filings([good, bad])

    assert successful_ids == ["house_11111111"]
    assert len(trades) == 1
    assert trades[0]["filing_id"] == "house_11111111"


def test_download_pdf_raises_filing_fetch_error_on_bad_status():
    fake_response = MagicMock()
    fake_response.status_code = 503

    with patch("requests.get", return_value=fake_response):
        with pytest.raises(parser_module.FilingFetchError):
            parser_module.download_pdf("https://example.com/whatever.pdf")


def test_parse_senate_filing_raises_filing_fetch_error_on_bad_status():
    fake_response = MagicMock()
    fake_response.status_code = 500

    filing = {"filing_id": "senate_x", "pdf_url": "https://efdsearch.senate.gov/x"}

    with patch("requests.get", return_value=fake_response):
        with pytest.raises(parser_module.FilingFetchError):
            parser_module.parse_senate_filing(filing)


# ─── main.py end-to-end: only successfully-parsed filings get marked seen ───

@pytest.fixture
def isolated_main_paths(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    seen_file = data_dir / "seen_trades.json"

    monkeypatch.setattr(main_module, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main_module, "RUN_LOG_FILE", str(data_dir / "run_log.txt"))
    monkeypatch.setattr(seen_store, "SEEN_TRADES_FILE", str(seen_file))
    monkeypatch.setattr(seen_store, "DATA_DIR", str(data_dir))

    return {"seen_file": seen_file}


def test_run_only_marks_successfully_parsed_filings_as_seen(isolated_main_paths, monkeypatch):
    good_filing = {"filing_id": "house_11111111", "representative": "Good"}
    bad_filing = {"filing_id": "house_22222222", "representative": "Bad"}

    monkeypatch.setattr(main_module, "get_new_trades", lambda: [good_filing, bad_filing])
    monkeypatch.setattr(main_module, "get_new_senate_trades", lambda: [])

    def fake_parse_all_filings(filings):
        # Simulate: the "bad" filing's download failed transiently and was
        # skipped, only the "good" one was actually parsed successfully.
        return [{"asset": "Apple Inc", "filing_id": "house_11111111"}], ["house_11111111"]

    monkeypatch.setattr(main_module, "parse_all_filings", fake_parse_all_filings)
    monkeypatch.setattr(main_module, "enrich_trades", lambda: None)
    monkeypatch.setattr(main_module, "score_trades", lambda: [])
    monkeypatch.setattr(main_module, "send_report", lambda *args, **kwargs: True)

    main_module.run()

    seen = seen_store.load_seen_trades()
    assert seen == {"house_11111111"}
    assert "house_22222222" not in seen


def test_run_marks_nothing_seen_when_parser_raises_entirely(isolated_main_paths, monkeypatch):
    """
    If parse_all_filings itself blows up (not a per-filing FilingFetchError,
    but a totally unexpected exception), main.py's existing outer try/except
    catches it and leaves parsed_filing_ids empty — nothing should be marked
    seen, so every discovered filing is retried next run.
    """
    filing = {"filing_id": "house_33333333", "representative": "Whoever"}

    monkeypatch.setattr(main_module, "get_new_trades", lambda: [filing])
    monkeypatch.setattr(main_module, "get_new_senate_trades", lambda: [])

    def raising_parse_all_filings(filings):
        raise RuntimeError("totally unexpected parser crash")

    monkeypatch.setattr(main_module, "parse_all_filings", raising_parse_all_filings)
    monkeypatch.setattr(main_module, "send_report", lambda *args, **kwargs: True)

    main_module.run()

    assert seen_store.load_seen_trades() == set()
