"""Per-page text from PDFs with poppler, OCR for pages without a text layer.

Each page is read twice with `pdftotext`: with `-layout` (keeps table columns;
this is what the reading model sees) and in reading order (keeps prose columns
together; used when checking quotes). Pages whose text layer is empty or
nearly so are OCRed with `ocrmypdf --skip-text` when it is installed (CI), or
with `pdftoppm` + `tesseract`; otherwise they are marked `needs_ocr`.

Every page records how its text was obtained: "pdf_text", "ocr" or "none".
Text produced here lives only in the gitignored .cache (CLAUDE.md rule 3).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

OcrFn = Callable[[Path, list[int]], dict[int, tuple[str, str]]]


def _run(cmd: list[str], timeout: int = 600) -> str:
    out = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {out.stderr.decode('utf-8', 'replace')[:300]}")
    return out.stdout.decode("utf-8", "replace")


def page_count(path: Path) -> int:
    m = re.search(r"^Pages:\s+(\d+)", _run(["pdfinfo", str(path)]), re.M)
    if not m:
        raise RuntimeError(f"pdfinfo gave no page count for {path}")
    return int(m.group(1))


def page_text(path: Path, n: int, layout: bool = True) -> str:
    cmd = ["pdftotext", "-q", "-f", str(n), "-l", str(n), "-enc", "UTF-8"]
    if layout:
        cmd.append("-layout")
    return _run(cmd + [str(path), "-"]).replace("\f", "")


def has_text(text: str, min_chars: int = 25) -> bool:
    return len(re.sub(r"\s+", "", text or "")) >= min_chars


# --- OCR -------------------------------------------------------------------

def ocr_engine() -> str | None:
    if shutil.which("ocrmypdf"):
        return "ocrmypdf"
    if shutil.which("tesseract") and shutil.which("pdftoppm"):
        return "tesseract"
    return None


def ocr_pages(path: Path, page_numbers: list[int], language: str = "eng", timeout: int = 900,
              dpi: int = 300) -> dict[int, tuple[str, str]]:
    """{page: (layout text, reading-order text)} for the given 1-based pages."""
    engine = ocr_engine()
    if engine is None or not page_numbers:
        return {}
    out: dict[int, tuple[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="scgeo-ocr-") as tmp:
        if engine == "ocrmypdf":
            dest = Path(tmp) / "ocr.pdf"
            subprocess.run(["ocrmypdf", "--skip-text", "--output-type", "pdf", "--optimize", "0", "-l", language,
                            "--tesseract-timeout", str(timeout), "--max-image-mpixels", "0", "--quiet",
                            str(path), str(dest)], capture_output=True, timeout=timeout * 4, check=True)
            for n in page_numbers:
                out[n] = (page_text(dest, n), page_text(dest, n, layout=False))
            return out
        for n in page_numbers:
            stem = Path(tmp) / f"p{n}"
            subprocess.run(["pdftoppm", "-r", str(dpi), "-scale-to", "10000", "-f", str(n), "-l", str(n), "-png",
                            "-singlefile", str(path), str(stem)], capture_output=True, timeout=timeout, check=True)
            txt = _run(["tesseract", f"{stem}.png", "-", "-l", language, "--psm", "3"], timeout=timeout)
            out[n] = (txt, txt)
    return out


# --- documents ----------------------------------------------------------------

def extract(path: Path, ocr: OcrFn | str | None = "auto", min_chars: int = 25) -> list[dict]:
    """One dict per page: file_page, text (layout), raw (reading order), method, needs_ocr."""
    path = Path(path)
    pages = []
    for n in range(1, page_count(path) + 1):
        text = page_text(path, n)
        ok = has_text(text, min_chars)
        pages.append({"file_page": n, "text": text, "raw": page_text(path, n, layout=False) if ok else "",
                      "method": "pdf_text" if ok else "none", "needs_ocr": not ok})
    todo = [p["file_page"] for p in pages if p["needs_ocr"]]
    if todo and ocr is not None:
        fn = ocr_pages if ocr == "auto" else ocr
        try:
            done = fn(path, todo)
        except (RuntimeError, OSError, subprocess.SubprocessError):
            done = {}
        for p in pages:
            if p["file_page"] in done:
                layout, raw = done[p["file_page"]]
                p.update(text=layout, raw=raw, method="ocr", needs_ocr=False)
    return pages


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def document(source_id: str, files: list[dict], ocr: OcrFn | str | None = "auto", min_chars: int = 25) -> dict:
    """Text for a whole document. Pages are numbered 1..N across all its files in order."""
    doc = {"source_id": source_id, "files": [], "pages": []}
    for i, f in enumerate(files):
        pages = extract(Path(f["path"]), ocr=ocr, min_chars=min_chars)
        doc["files"].append({"url": f.get("url"), "path": str(f["path"]), "sha256": sha256(Path(f["path"])),
                             "pages": len(pages), "first_page": len(doc["pages"]) + 1, "via": f.get("via")})
        for p in pages:
            doc["pages"].append({"page": len(doc["pages"]) + 1, "file": i, **p})
    return doc
