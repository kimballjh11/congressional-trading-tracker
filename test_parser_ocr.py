# test_parser_ocr.py — Regression tests for the OCR fallback added to
# parser.py (ocr_extract_text_from_pdf, save_ocr_text_for_manual_review,
# and the resulting branch in parse_house_filing).
#
# Named distinctly from test_parser.py / test_parser_pdf_diagnostics.py to
# avoid filename collisions with other in-flight branches.

import io
import os
import sys
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch, MagicMock

import parser as parser_module
from parser import (
    ocr_extract_text_from_pdf,
    save_ocr_text_for_manual_review,
    parse_house_filing,
)


def _install_fake_ocr_modules(page_texts):
    """
    Installs fake `pypdfium2`/`pytesseract` modules into sys.modules so
    `ocr_extract_text_from_pdf`'s dynamic `import pypdfium2` / `import
    pytesseract` succeed and return controllable, deterministic output —
    without needing the real Tesseract binary in the test environment.
    """
    fake_pages = []
    for text in page_texts:
        page = MagicMock()
        bitmap = MagicMock()
        bitmap.to_pil.return_value = f"<image for {text!r}>"
        page.render.return_value = bitmap
        fake_pages.append(page)

    fake_pdf_doc = MagicMock()
    fake_pdf_doc.__iter__ = lambda self: iter(fake_pages)

    fake_pdfium = types.ModuleType("pypdfium2")
    fake_pdfium.PdfDocument = MagicMock(return_value=fake_pdf_doc)

    fake_pytesseract = types.ModuleType("pytesseract")
    text_iter = iter(page_texts)
    fake_pytesseract.image_to_string = MagicMock(side_effect=lambda img: next(text_iter))

    return fake_pdfium, fake_pytesseract, fake_pdf_doc, fake_pages


class TestOcrExtractTextFromPdf(unittest.TestCase):
    def test_returns_empty_string_when_ocr_libraries_missing(self):
        pdf_bytes = io.BytesIO(b"fake")
        with patch.dict(sys.modules, {"pypdfium2": None, "pytesseract": None}):
            self.assertEqual(ocr_extract_text_from_pdf(pdf_bytes), "")

    def test_joins_text_from_all_pages_in_order(self):
        pdf_bytes = io.BytesIO(b"fake")
        fake_pdfium, fake_pytesseract, fake_pdf_doc, fake_pages = _install_fake_ocr_modules(
            ["page one text", "page two text"]
        )
        with patch.dict(sys.modules, {"pypdfium2": fake_pdfium, "pytesseract": fake_pytesseract}):
            text = ocr_extract_text_from_pdf(pdf_bytes)

        self.assertEqual(text, "page one text\npage two text\n")
        fake_pdf_doc.close.assert_called_once()
        for page in fake_pages:
            page.close.assert_called_once()

    def test_skips_pages_with_no_recognized_text(self):
        pdf_bytes = io.BytesIO(b"fake")
        fake_pdfium, fake_pytesseract, _, _ = _install_fake_ocr_modules(["", "some text"])
        with patch.dict(sys.modules, {"pypdfium2": fake_pdfium, "pytesseract": fake_pytesseract}):
            text = ocr_extract_text_from_pdf(pdf_bytes)

        self.assertEqual(text, "some text\n")

    def test_seeks_back_to_start_before_rendering(self):
        pdf_bytes = io.BytesIO(b"fake")
        pdf_bytes.read()  # simulate having already been consumed by extract_text_from_pdf
        fake_pdfium, fake_pytesseract, _, _ = _install_fake_ocr_modules(["text"])
        with patch.dict(sys.modules, {"pypdfium2": fake_pdfium, "pytesseract": fake_pytesseract}):
            ocr_extract_text_from_pdf(pdf_bytes)
        fake_pdfium.PdfDocument.assert_called_once_with(pdf_bytes)
        self.assertEqual(pdf_bytes.tell(), 0)

    def test_returns_empty_string_on_render_failure_not_raises(self):
        pdf_bytes = io.BytesIO(b"not a real pdf")
        fake_pdfium = types.ModuleType("pypdfium2")
        fake_pdfium.PdfDocument = MagicMock(side_effect=Exception("corrupt"))
        fake_pytesseract = types.ModuleType("pytesseract")
        with patch.dict(sys.modules, {"pypdfium2": fake_pdfium, "pytesseract": fake_pytesseract}):
            self.assertEqual(ocr_extract_text_from_pdf(pdf_bytes), "")


class TestSaveOcrTextForManualReview(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.patcher = patch.object(parser_module, "OCR_UNPARSED_DIR", self.tmp_dir)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_writes_file_and_returns_path(self):
        path = save_ocr_text_for_manual_review("house_9115812", "some OCR text")
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            self.assertEqual(f.read(), "some OCR text")

    def test_sanitizes_unsafe_characters_in_filing_id(self):
        path = save_ocr_text_for_manual_review(
            "house_public_disc/ptr-pdfs/2026/9115812.pdf", "text"
        )
        self.assertTrue(os.path.isfile(path))
        self.assertNotIn("/", os.path.basename(path))


class TestParseHouseFilingOcrBranch(unittest.TestCase):
    def _filing(self, filing_id="house_9115812"):
        return {
            "representative": "Test Rep",
            "state_district": "XX00",
            "filing_id": filing_id,
            "pdf_url": "https://example.com/fake.pdf",
        }

    @patch("parser.save_ocr_text_for_manual_review", return_value="/tmp/fake_path.txt")
    @patch("parser.parse_trades_from_text", return_value=[])
    @patch("parser.ocr_extract_text_from_pdf", return_value="garbled ocr text")
    @patch("parser.extract_text_from_pdf", return_value="")
    @patch("parser.download_pdf", return_value=io.BytesIO(b"fake"))
    def test_ocr_recovers_text_but_no_trades_saves_for_manual_review(
        self, mock_download, mock_extract, mock_ocr, mock_parse_trades, mock_save
    ):
        with patch("builtins.print") as mock_print:
            trades = parse_house_filing(self._filing())
            self.assertEqual(trades, [])
            mock_save.assert_called_once_with(self._filing()["filing_id"], "garbled ocr text")
            printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
            self.assertIn("manual review", printed)

    @patch("parser.save_ocr_text_for_manual_review")
    @patch(
        "parser.parse_trades_from_text",
        return_value=[{"owner": "", "asset": "Acme Corp", "ticker": "ACME"}],
    )
    @patch("parser.ocr_extract_text_from_pdf", return_value="clean enough ocr text")
    @patch("parser.extract_text_from_pdf", return_value="")
    @patch("parser.download_pdf", return_value=io.BytesIO(b"fake"))
    def test_ocr_recovers_parseable_trades_does_not_save_for_manual_review(
        self, mock_download, mock_extract, mock_ocr, mock_parse_trades, mock_save
    ):
        trades = parse_house_filing(self._filing())
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["asset"], "Acme Corp")
        mock_save.assert_not_called()

    @patch("parser.parse_trades_from_text")
    @patch("parser.ocr_extract_text_from_pdf", return_value="")
    @patch("parser.extract_text_from_pdf", return_value="")
    @patch("parser.download_pdf", return_value=io.BytesIO(b"fake"))
    def test_ocr_failure_returns_empty_without_calling_trade_parser(
        self, mock_download, mock_extract, mock_ocr, mock_parse_trades
    ):
        with patch("builtins.print") as mock_print:
            trades = parse_house_filing(self._filing())
            self.assertEqual(trades, [])
            mock_parse_trades.assert_not_called()
            printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
            self.assertIn("unrecoverable", printed)

    @patch("parser.ocr_extract_text_from_pdf")
    @patch("parser.parse_trades_from_text", return_value=[{"owner": "", "asset": "Foo"}])
    @patch("parser.extract_text_from_pdf", return_value="normal pdfplumber text")
    @patch("parser.download_pdf", return_value=io.BytesIO(b"fake"))
    def test_normal_text_layer_never_triggers_ocr(
        self, mock_download, mock_extract, mock_parse_trades, mock_ocr
    ):
        trades = parse_house_filing(self._filing())
        self.assertEqual(len(trades), 1)
        mock_ocr.assert_not_called()


if __name__ == "__main__":
    unittest.main()
