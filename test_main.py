# test_main.py — tests for main.py's seen-filing bookkeeping
#
# Regression coverage for: main.py used to call mark_filings_seen(all_filings)
# with every filing the scrapers found, regardless of whether parse_all_filings()
# actually succeeded in fetching/parsing each one. A filing whose report
# download failed (network error, Senate EFDS bot-detection 403, etc.) would
# get permanently marked "seen" anyway just for being in the same batch as
# filings that genuinely had zero trades or succeeded normally — losing that
# filing's data forever with no retry. main.py must use parse_all_filings()'s
# returned successful_filing_ids, not the raw scraped filing list.

from unittest.mock import patch

import main


def _reset_counters():
    pass


def test_mark_filings_seen_uses_only_filing_ids(tmp_path, monkeypatch):
    seen_file = tmp_path / "seen_trades.json"
    monkeypatch.setattr(main, "SEEN_TRADES_FILE", str(seen_file), raising=False)

    import scraper as scraper_module
    monkeypatch.setattr(scraper_module, "SEEN_TRADES_FILE", str(seen_file))

    main.mark_filings_seen(["house_1", "senate_2"])

    seen = scraper_module.load_seen_trades()
    assert seen == {"house_1", "senate_2"}


def test_run_does_not_mark_failed_download_filing_as_seen(tmp_path, monkeypatch):
    """
    End-to-end-ish: STEP 1 returns 2 filings, STEP 2 (parse) only succeeds
    for one of them (the other raised FilingFetchError internally and was
    swallowed by parse_all_filings, which is mocked here to return the
    post-fix tuple shape directly). The failed filing's ID must never reach
    the seen-store.
    """
    seen_file = tmp_path / "seen_trades.json"
    import scraper as scraper_module
    monkeypatch.setattr(scraper_module, "SEEN_TRADES_FILE", str(seen_file))
    monkeypatch.setattr(main, "RUN_LOG_FILE", str(tmp_path / "run_log.txt"))
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    house_filing = {"filing_id": "house_111", "representative": "A", "chamber": "House"}
    senate_filing_that_fails = {"filing_id": "senate_222", "representative": "B", "chamber": "Senate"}

    with patch.object(main, "get_new_trades", return_value=[house_filing]), \
         patch.object(main, "get_new_senate_trades", return_value=[senate_filing_that_fails]), \
         patch.object(
             main, "parse_all_filings",
             return_value=([{"ticker": "FOO", "representative": "A"}], ["house_111"]),
         ), \
         patch.object(main, "enrich_trades", return_value=None), \
         patch.object(
             main, "score_trades",
             return_value=[{"ticker": "FOO", "representative": "A", "score": 10, "tag": "routine"}],
         ), \
         patch.object(main, "send_report", return_value=True):
        main.run()

    seen = scraper_module.load_seen_trades()
    assert "house_111" in seen
    assert "senate_222" not in seen
