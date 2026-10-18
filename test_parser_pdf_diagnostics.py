# test_parser_pdf_diagnostics.py — Regression tests for is_image_only_pdf() and the
# distinguishing log message in parse_house_filing() for image-only (scanned) PDFs.
#
# Named distinctly from test_parser.py to avoid filename collisions with other
# in-flight branches that also add a test_parser.py.

import io
import unittest
from unittest.mock import patch, MagicMock

from parser import is_image_only_pdf, parse_house_filing


class FakePage:
    def __init__(self, text=None, images=None):
        self._text = text
        self.images = images if images is not None else []

    def extract_text(self):
        return self._text


class FakePDF:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestIsImageOnlyPdf(unittest.TestCase):
    def test_scanned_pdf_with_image_and_no_text(self):
        pdf_bytes = io.BytesIO(b"fake")
        fake_pdf = FakePDF([FakePage(text=None, images=[{"x0": 0}])])
        with patch("parser.pdfplumber.open", return_value=fake_pdf):
            self.assertTrue(is_image_only_pdf(pdf_bytes))

    def test_pdf_with_no_images_returns_false(self):
        pdf_bytes = io.BytesIO(b"fake")
        fake_pdf = FakePDF([FakePage(text=None, images=[])])
        with patch("parser.pdfplumber.open", return_value=fake_pdf):
            self.assertFalse(is_image_only_pdf(pdf_bytes))

    def test_seeks_back_to_start_before_reopening(self):
        pdf_bytes = io.BytesIO(b"fake")
        pdf_bytes.read()  # simulate having already been consumed by extract_text_from_pdf
        fake_pdf = FakePDF([FakePage(text=None, images=[{"x0": 0}])])
        with patch("parser.pdfplumber.open", return_value=fake_pdf) as mock_open:
            is_image_only_pdf(pdf_bytes)
            mock_open.assert_called_once()
        self.assertEqual(pdf_bytes.tell(), 0)

    def test_corrupt_pdf_returns_false_not_raises(self):
        pdf_bytes = io.BytesIO(b"not a real pdf")
        with patch("parser.pdfplumber.open", side_effect=Exception("corrupt")):
            self.assertFalse(is_image_only_pdf(pdf_bytes))


class TestParseHouseFilingLogging(unittest.TestCase):
    def _filing(self, filing_id="house_9115812"):
        return {
            "representative": "Test Rep",
            "state_district": "XX00",
            "filing_id": filing_id,
            "pdf_url": "https://example.com/fake.pdf",
        }

    @patch("parser.is_image_only_pdf", return_value=True)
    @patch("parser.extract_text_from_pdf", return_value="")
    @patch("parser.download_pdf", return_value=io.BytesIO(b"fake"))
    def test_image_only_pdf_returns_empty_trades_and_distinguishing_message(
        self, mock_download, mock_extract, mock_image_only
    ):
        with patch("builtins.print") as mock_print:
            trades = parse_house_filing(self._filing())
            self.assertEqual(trades, [])
            printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
            self.assertIn("image-only", printed)
            self.assertIn("house_9115812", printed)

    @patch("parser.is_image_only_pdf", return_value=False)
    @patch("parser.extract_text_from_pdf", return_value="")
    @patch("parser.download_pdf", return_value=io.BytesIO(b"fake"))
    def test_generic_extraction_failure_keeps_generic_message(
        self, mock_download, mock_extract, mock_image_only
    ):
        with patch("builtins.print") as mock_print:
            trades = parse_house_filing(self._filing("house_other"))
            self.assertEqual(trades, [])
            printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
            self.assertNotIn("image-only", printed)
            self.assertIn("No text extracted", printed)


if __name__ == "__main__":
    unittest.main()
