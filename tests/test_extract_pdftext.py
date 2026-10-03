import shutil

import pytest

from extract import pdftext
from tests.pdfgen import make_pdf

pytestmark = pytest.mark.skipif(not shutil.which("pdftotext") or not shutil.which("pdfinfo"),
                                reason="poppler-utils not installed")


@pytest.fixture
def pdf(tmp_path):
    return make_pdf(tmp_path / "doc.pdf", [
        ["Geology of the Charleston quadrangle", "Wando Formation (late Pleistocene)"],
        [],
        ["Auger hole 12: 0-4 ft sand, 10YR 5/6"],
    ])


def test_page_count(pdf):
    assert pdftext.page_count(pdf) == 3


def test_page_text_layout_and_raw(pdf):
    assert "Wando Formation" in pdftext.page_text(pdf, 1)
    assert "Auger hole 12" in pdftext.page_text(pdf, 3, layout=False)
    assert pdftext.page_text(pdf, 2).strip() == ""


def test_has_text_threshold():
    assert not pdftext.has_text("  \f\n ", 25)
    assert not pdftext.has_text("12", 25)
    assert pdftext.has_text("x" * 30, 25)


def test_pages_without_text_marked_when_no_ocr(pdf):
    pages = pdftext.extract(pdf, ocr=None)
    assert [p["file_page"] for p in pages] == [1, 2, 3]
    assert [p["method"] for p in pages] == ["pdf_text", "none", "pdf_text"]
    assert pages[1]["needs_ocr"] is True
    assert pages[0]["needs_ocr"] is False


def test_pages_without_text_are_ocred(pdf):
    calls = []

    def fake_ocr(path, page_numbers):
        calls.append(list(page_numbers))
        return {n: ("Clay, gray, 5Y 4/1", "Clay, gray, 5Y 4/1") for n in page_numbers}

    pages = pdftext.extract(pdf, ocr=fake_ocr)
    assert calls == [[2]]  # only the textless page
    assert pages[1]["method"] == "ocr"
    assert "5Y 4/1" in pages[1]["text"]
    assert pages[0]["method"] == "pdf_text"


def test_document_numbers_pages_across_files(tmp_path, pdf):
    second = make_pdf(tmp_path / "sheet2.pdf", [["Cross section A-A'"]])
    doc = pdftext.document("ngmdb:1", [{"url": "https://x/1.pdf", "path": str(pdf)},
                                       {"url": "https://x/2.pdf", "path": str(second)}], ocr=None)
    assert doc["source_id"] == "ngmdb:1"
    assert [p["page"] for p in doc["pages"]] == [1, 2, 3, 4]
    assert doc["pages"][3]["file"] == 1 and doc["pages"][3]["file_page"] == 1
    assert doc["files"][1]["first_page"] == 4
    assert doc["files"][0]["pages"] == 3
    assert len(doc["files"][0]["sha256"]) == 64


def test_ocr_available_reports_tools(monkeypatch):
    monkeypatch.setattr(pdftext.shutil, "which", lambda name: None)
    assert pdftext.ocr_engine() is None
    monkeypatch.setattr(pdftext.shutil, "which", lambda name: "/usr/bin/" + name if name == "tesseract" else None)
    assert pdftext.ocr_engine() is None  # tesseract also needs pdftoppm
    monkeypatch.setattr(pdftext.shutil, "which", lambda name: "/usr/bin/" + name)
    assert pdftext.ocr_engine() == "ocrmypdf"
