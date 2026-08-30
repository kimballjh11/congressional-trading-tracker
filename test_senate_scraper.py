# test_senate_scraper.py — regression tests for senate_scraper.py's
# DataTables pagination in search_ptr_filings().
#
# Bug being tested: search_ptr_filings() paginates the Senate EFDS
# DataTables API by requesting `start=<offset>` on each page. The offset
# must track how many rows have actually been *requested* from the
# server so far. The old code instead used `len(filings)` — the count of
# rows that successfully turned into a filing dict — as that offset.
# Since `parse_search_row()` can return None for a row (malformed row,
# or a report type that slips past the server-side filter), those two
# counts can diverge whenever a result set spans more than one 100-row
# page, causing already-seen rows to be re-requested (and re-added as
# duplicate filings) instead of the pagination cursor advancing.

import json
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, ".")
import senate_scraper as ss


def make_ptr_row(row_id):
    """A well-formed row that parse_search_row() will accept."""
    return [
        "Jane",
        f"Member{row_id}",
        "CA",
        f'<a href="/search/view/ptr/{row_id:08d}-0000-0000-0000-000000000000/">'
        f"Periodic Transaction Report</a>",
        "01/01/2026",
    ]


def make_fake_session(all_rows, total=None):
    """
    A mock session whose .post() serves slices of `all_rows` according to
    the DataTables `start`/`length` params, mimicking the real EFDS API.
    """
    if total is None:
        total = len(all_rows)

    session = MagicMock()
    session.cookies.get.return_value = "fake-csrf-token"

    requested_starts = []

    def post_side_effect(url, data=None, headers=None):
        start = int(data["start"])
        length = int(data["length"])
        requested_starts.append(start)

        page_rows = all_rows[start:start + length]
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        resp.json.return_value = {"recordsTotal": total, "data": page_rows}
        return resp

    session.post.side_effect = post_side_effect
    session._requested_starts = requested_starts
    return session


class TestSearchPtrFilingsPagination(unittest.TestCase):
    def test_single_page_under_100_rows(self):
        rows = [make_ptr_row(i) for i in range(30)]
        session = make_fake_session(rows)

        filings = ss.search_ptr_filings(session, "01/01/2026", "02/01/2026")

        self.assertEqual(len(filings), 30)
        self.assertEqual(session._requested_starts, [0])

    def test_multi_page_all_rows_valid(self):
        rows = [make_ptr_row(i) for i in range(250)]
        session = make_fake_session(rows)

        filings = ss.search_ptr_filings(session, "01/01/2026", "02/01/2026")

        self.assertEqual(len(filings), 250)
        self.assertEqual(len(set(f["filing_id"] for f in filings)), 250)
        # Offsets must advance by rows *fetched*, not rows *kept*.
        self.assertEqual(session._requested_starts, [0, 100, 200])

    def test_multi_page_with_malformed_rows_no_duplicates(self):
        """
        Regression test for the offset-drift bug: malformed rows near a
        page boundary used to cause the next page's `start` to lag behind
        the true row count, re-fetching (and re-adding, as duplicates)
        rows already parsed on the previous page.
        """
        rows = [make_ptr_row(i) for i in range(150)]
        # Malformed rows (too few fields) land inside the first page and
        # would have shifted `len(filings)` away from the true offset.
        for bad_index in (3, 47, 90):
            rows[bad_index] = ["too", "short"]

        session = make_fake_session(rows)
        filings = ss.search_ptr_filings(session, "01/01/2026", "02/01/2026")

        expected_valid = 150 - 3
        self.assertEqual(len(filings), expected_valid)
        self.assertEqual(len(set(f["filing_id"] for f in filings)), expected_valid)
        # The fixed code must always advance the offset by the number of
        # rows it actually asked for (100), regardless of how many of
        # those rows were dropped by parse_search_row().
        self.assertEqual(session._requested_starts, [0, 100])

    def test_many_malformed_rows_across_several_pages(self):
        total = 320
        rows = [make_ptr_row(i) for i in range(total)]
        malformed = set(range(0, total, 7))
        for i in malformed:
            rows[i] = ["too", "short"]

        session = make_fake_session(rows)
        filings = ss.search_ptr_filings(session, "01/01/2026", "02/01/2026")

        expected_valid = total - len(malformed)
        self.assertEqual(len(filings), expected_valid)
        self.assertEqual(len(set(f["filing_id"] for f in filings)), expected_valid)
        self.assertEqual(session._requested_starts, [0, 100, 200, 300])

    def test_maintenance_page_mid_pagination_stops_cleanly(self):
        rows = [make_ptr_row(i) for i in range(250)]
        session = make_fake_session(rows)

        real_side_effect = session.post.side_effect
        call_count = {"n": 0}

        def flaky_side_effect(url, data=None, headers=None):
            call_count["n"] += 1
            if call_count["n"] == 2:
                resp = MagicMock()
                resp.status_code = 200
                resp.text = "Site Under Maintenance"
                return resp
            return real_side_effect(url, data=data, headers=headers)

        session.post.side_effect = flaky_side_effect

        filings = ss.search_ptr_filings(session, "01/01/2026", "02/01/2026")

        # First page (100 rows) succeeded before maintenance kicked in.
        self.assertEqual(len(filings), 100)
        self.assertEqual(len(set(f["filing_id"] for f in filings)), 100)


if __name__ == "__main__":
    unittest.main()
