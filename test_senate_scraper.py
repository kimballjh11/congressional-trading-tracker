# test_senate_scraper.py — Regression tests for senate_scraper.py's
# DataTables pagination logic.

from unittest.mock import MagicMock

import senate_scraper


def _build_rows(count, non_ptr_indices=()):
    """Build fake DataTables rows. Rows at `non_ptr_indices` are a non-PTR
    report type, so `parse_search_row()` will filter them out (return None)."""
    rows = []
    for i in range(count):
        if i in non_ptr_indices:
            rows.append(
                ["First", "Last", "Office", '<a href="/x">Annual Report</a>', "01/01/2026"]
            )
        else:
            rows.append(
                [
                    "First",
                    f"Last{i}",
                    "Office",
                    f'<a href="/search/view/ptr/{i:08x}-0000-0000-0000-000000000000/">'
                    f"Periodic Transaction Report</a>",
                    "01/01/2026",
                ]
            )
    return rows


def _make_session(all_rows, page_size):
    """Build a fake `requests.Session` whose `.post()` serves `all_rows`
    paginated by `page_size`, honoring the `start` offset passed in `data`."""
    call_log = []

    def fake_post(url, data=None, headers=None, timeout=None):
        start = int(data["start"])
        call_log.append(start)
        page = all_rows[start : start + page_size]
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        resp.json.return_value = {"recordsTotal": len(all_rows), "data": page}
        return resp

    session = MagicMock()
    session.post.side_effect = fake_post
    session.cookies.get.return_value = "token"
    return session, call_log


def test_pagination_with_no_filtered_rows_is_unaffected():
    """Sanity check: when every row parses into a filing, pagination
    advances normally regardless of which offset variable is used."""
    rows = _build_rows(10)
    session, call_log = _make_session(rows, page_size=4)

    filings = senate_scraper.search_ptr_filings(
        session, start_date="01/01/2026", end_date="01/02/2026"
    )

    assert len(filings) == 10
    assert len(set(f["filing_id"] for f in filings)) == 10
    assert call_log == [0, 4, 8]


def test_pagination_does_not_duplicate_filings_when_rows_are_filtered():
    """Regression test: when some rows are filtered out by
    `parse_search_row()` (e.g. a non-PTR report type), the next page's
    `start` offset must be based on the number of rows actually consumed
    from the server, not on `len(filings)` — otherwise the same rows get
    re-requested and duplicated in the result."""
    rows = _build_rows(10, non_ptr_indices=(2, 5))
    session, call_log = _make_session(rows, page_size=4)

    filings = senate_scraper.search_ptr_filings(
        session, start_date="01/01/2026", end_date="01/02/2026"
    )

    expected_count = 10 - 2  # 2 rows filtered out as non-PTR
    assert len(filings) == expected_count
    assert len(set(f["filing_id"] for f in filings)) == expected_count
    # Offsets must advance by rows actually fetched (4, 4), not by
    # filings kept — i.e. [0, 4, 8], never anything smaller like [0, 3, 6].
    assert call_log == [0, 4, 8]


def test_pagination_offset_drift_does_not_cause_mass_duplication():
    """Wider regression check: a higher filter rate (1/3 of rows are
    non-PTR) across many pages must still produce exactly as many unique
    filings as real PTR rows exist, with no duplicates."""
    rows = _build_rows(20, non_ptr_indices=tuple(i for i in range(20) if i % 3 == 0))
    session, call_log = _make_session(rows, page_size=5)

    filings = senate_scraper.search_ptr_filings(
        session, start_date="01/01/2026", end_date="01/02/2026"
    )

    expected_count = sum(1 for i in range(20) if i % 3 != 0)
    assert len(filings) == expected_count
    assert len(set(f["filing_id"] for f in filings)) == expected_count
    assert call_log == [0, 5, 10, 15]
