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


# --- OCR reliability (subprocess mocked, so these are fast) ---------------------

class FakeRun:
    """Stands in for subprocess.run: pdftoppm succeeds, tesseract fails on chosen pages."""

    def __init__(self, fail=(), exc="timeout"):
        self.fail, self.exc, self.calls = set(fail), exc, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[0] == "tesseract":
            n = int(pdftext.Path(cmd[1]).stem[1:])
            if n in self.fail:
                if self.exc == "error":
                    return pdftext.subprocess.CompletedProcess(cmd, 1, b"", b"tesseract crashed")
                raise pdftext.subprocess.TimeoutExpired(cmd, kw.get("timeout"))
            return pdftext.subprocess.CompletedProcess(cmd, 0, f"Sand and clay, page {n}".encode(), b"")
        return pdftext.subprocess.CompletedProcess(cmd, 0, b"", b"")


@pytest.fixture
def tesseract_only(monkeypatch):
    monkeypatch.setattr(pdftext, "ocr_engine", lambda: "tesseract")
    monkeypatch.setattr(pdftext, "native_dpi", lambda path, n: 400)


@pytest.mark.parametrize("exc", ["timeout", "error"])
def test_one_failing_page_does_not_discard_the_others(tmp_path, monkeypatch, tesseract_only, exc):
    run = FakeRun(fail={2}, exc=exc)
    monkeypatch.setattr(pdftext.subprocess, "run", run)
    done = pdftext.ocr_pages(tmp_path / "scan.pdf", [1, 2, 3])
    assert sorted(done) == [1, 3]
    assert "page 3" in done[3][0]


def test_tesseract_render_is_capped_and_single_threaded(tmp_path, monkeypatch, tesseract_only):
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)
    run = FakeRun()
    monkeypatch.setattr(pdftext.subprocess, "run", run)
    pdftext.ocr_pages(tmp_path / "scan.pdf", [1], timeout=42)
    render = next(c for c, kw in run.calls if c[0] == "pdftoppm")
    assert render[render.index("-scale-to") + 1] == "8000"
    assert render[render.index("-r") + 1] == "400"
    tess_kw = next(kw for c, kw in run.calls if c[0] == "tesseract")
    assert tess_kw["env"]["OMP_THREAD_LIMIT"] == "1"
    assert all(kw["timeout"] == 42 for c, kw in run.calls)


def test_ocr_pages_caches_each_page_and_reuses_it(tmp_path, monkeypatch, tesseract_only):
    cache = tmp_path / "ocr" / "abc"
    monkeypatch.setattr(pdftext.subprocess, "run", FakeRun(fail={2}))
    pdftext.ocr_pages(tmp_path / "scan.pdf", [1, 2, 3], cache=cache)
    assert sorted(p.name for p in cache.iterdir()) == ["p1.txt", "p3.txt"]

    run2 = FakeRun()
    monkeypatch.setattr(pdftext.subprocess, "run", run2)
    done = pdftext.ocr_pages(tmp_path / "scan.pdf", [1, 2, 3], cache=cache)
    assert sorted(done) == [1, 2, 3]
    tess = [c[1] for c, kw in run2.calls if c[0] == "tesseract"]
    assert len(tess) == 1 and tess[0].endswith("p2.png")  # only the page that failed before


def test_extract_keeps_partial_ocr_and_resumes_from_cache(tmp_path):
    pdf = make_pdf(tmp_path / "scan.pdf", [[], ["Wando Formation (late Pleistocene) clayey sand"], [], []])
    calls = []

    def flaky(path, page_numbers):
        calls.append(list(page_numbers))
        return {n: (f"OCR text of page {n}, silty clay", f"raw {n}") for n in page_numbers if n != 4}

    cache = tmp_path / ".cache" / "ocr"
    pages = pdftext.extract(pdf, ocr=flaky, ocr_cache=cache)
    assert [p["method"] for p in pages] == ["ocr", "pdf_text", "ocr", "none"]
    assert pages[3]["needs_ocr"] is True
    sub = cache / pdftext.sha256(pdf)
    assert (sub / "p1.txt").exists() and (sub / "p3.txt").exists() and not (sub / "p4.txt").exists()

    pages = pdftext.extract(pdf, ocr=flaky, ocr_cache=cache)
    assert calls == [[1, 3, 4], [4]]  # finished pages are never OCRed again
    assert pages[0]["method"] == "ocr" and "page 1" in pages[0]["text"] and pages[0]["raw"] == "raw 1"


def test_document_passes_the_ocr_cache(tmp_path):
    pdf = make_pdf(tmp_path / "scan.pdf", [[]])
    fake = lambda path, pages: {n: ("Clay, gray, 5Y 4/1 with shells", "Clay") for n in pages}
    doc = pdftext.document("ngmdb:1", [{"url": "u", "path": str(pdf)}], ocr=fake, ocr_cache=tmp_path / "ocr")
    assert doc["pages"][0]["method"] == "ocr"
    assert (tmp_path / "ocr" / pdftext.sha256(pdf) / "p1.txt").exists()


def test_ocrmypdf_failure_falls_back_to_page_by_page(tmp_path, monkeypatch):
    monkeypatch.setattr(pdftext, "ocr_engine", lambda: "ocrmypdf")
    monkeypatch.setattr(pdftext.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(pdftext, "native_dpi", lambda path, n: None)
    fake = FakeRun(fail={2})

    def run(cmd, **kw):
        if cmd[0] == "ocrmypdf":
            raise pdftext.subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return fake(cmd, **kw)

    monkeypatch.setattr(pdftext.subprocess, "run", run)
    assert sorted(pdftext.ocr_pages(tmp_path / "scan.pdf", [1, 2])) == [1]
