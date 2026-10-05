"""Per-page text from PDFs with poppler, OCR for pages without a text layer.

Each page is read twice with `pdftotext`: with `-layout` (keeps table columns;
this is what the reading model sees) and in reading order (keeps prose columns
together; used when checking quotes). Pages whose text layer is empty or
nearly so are OCRed with `ocrmypdf --skip-text` when it is installed (CI), or
with `pdftoppm` + `tesseract`; otherwise they are marked `needs_ocr`. Pages are
OCRed one at a time: a page that fails or times out stays `needs_ocr` and the
others are kept. With an OCR cache (.cache/ocr) each finished page is saved and
reused on a rerun, so a retry only redoes the pages still missing.

Every page records how its text was obtained: "pdf_text", "ocr" or "none".
Text produced here lives only in the gitignored .cache (CLAUDE.md rule 3).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

OcrFn = Callable[[Path, list[int]], dict[int, tuple[str, str]]]
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "extract.json"


def _settings() -> dict:
    """The "ocr" block of config/extract.json (empty if unreadable)."""
    try:
        return json.loads(CONFIG_PATH.read_text()).get("ocr", {})
    except (OSError, ValueError):
        return {}


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


def native_dpi(path: Path, n: int) -> int | None:
    """Highest resolution (ppi) of the images on page n, so OCR renders scans at their own resolution."""
    try:
        out = _run(["pdfimages", "-list", "-f", str(n), "-l", str(n), str(path)], timeout=120)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return None
    ppis = []
    for line in out.splitlines()[2:]:
        cols = line.split()
        if len(cols) >= 14 and cols[12].isdigit():
            ppis.append(int(cols[12]))
    return max(ppis) if ppis else None


def ocr_page(path: Path, n: int, workdir: Path, language: str = "eng", timeout: int = 900, dpi: int = 300,
             max_pixels: int = 8000, threads: int | None = 1) -> tuple[str, str]:
    """Render page n with pdftoppm and read it with tesseract; raises on failure or timeout.

    The render uses the scan's own resolution (150-400 ppi) with its long side capped at
    max_pixels, so a large map sheet does not take hours. threads sets OMP_THREAD_LIMIT for
    tesseract (1 keeps parallel harvest workers from oversubscribing the CPU; None keeps the
    environment's setting).
    """
    stem = Path(workdir) / f"p{n}"
    native = native_dpi(path, n)
    render = min(max(native, 150), 400) if native else dpi
    subprocess.run(["pdftoppm", "-r", str(render), "-scale-to", str(max_pixels), "-f", str(n), "-l", str(n), "-png",
                    "-singlefile", str(path), str(stem)], capture_output=True, timeout=timeout, check=True)
    env = dict(os.environ)
    if threads is not None:
        env["OMP_THREAD_LIMIT"] = str(threads)
    try:
        out = subprocess.run(["tesseract", f"{stem}.png", "-", "-l", language, "--psm", "3"], capture_output=True,
                             timeout=timeout, env=env)
    finally:
        Path(f"{stem}.png").unlink(missing_ok=True)
    if out.returncode != 0:
        raise RuntimeError(f"tesseract failed: {out.stderr.decode('utf-8', 'replace')[:300]}")
    txt = out.stdout.decode("utf-8", "replace")
    return txt, txt


# Per-page OCR cache: <cache>/p<N>.txt (layout text) and, when it differs, p<N>.raw.txt.

def _cache_read(cache: Path | None, n: int) -> tuple[str, str] | None:
    if cache is None:
        return None
    p = Path(cache) / f"p{n}.txt"
    if not p.exists():
        return None
    layout = p.read_text(encoding="utf-8")
    raw = Path(cache) / f"p{n}.raw.txt"
    return layout, raw.read_text(encoding="utf-8") if raw.exists() else layout


def _cache_write(cache: Path | None, n: int, layout: str, raw: str) -> None:
    if cache is None:
        return
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    if raw != layout:
        tmp = cache / f"p{n}.raw.txt.tmp"
        tmp.write_text(raw, encoding="utf-8")
        tmp.replace(cache / f"p{n}.raw.txt")
    tmp = cache / f"p{n}.txt.tmp"  # written last and renamed, so a cached page is always complete
    tmp.write_text(layout, encoding="utf-8")
    tmp.replace(cache / f"p{n}.txt")


def ocr_pages(path: Path, page_numbers: list[int], language: str | None = None, timeout: int | None = None,
              dpi: int | None = None, max_pixels: int | None = None, threads: int | None = None,
              cache: Path | None = None, log: Callable[[str], None] | None = None) -> dict[int, tuple[str, str]]:
    """{page: (layout text, reading-order text)} for those of the given 1-based pages that could be OCRed.

    Each page is OCRed on its own: a page that fails or times out is left out (it stays
    needs_ocr) and the others are kept. With `cache`, each page is saved there as soon as it
    is done and reused on the next call, so a retry only redoes the pages that failed.
    Unset arguments come from the "ocr" block of config/extract.json; timeout is per page
    (env SC_GEO_OCR_TIMEOUT overrides it).
    """
    cfg = _settings()
    language = language or cfg.get("language", "eng")
    if timeout is None:
        timeout = int(os.environ.get("SC_GEO_OCR_TIMEOUT") or cfg.get("tesseract_timeout_seconds", 900))
    dpi = dpi or cfg.get("fallback_dpi", 300)
    max_pixels = max_pixels or cfg.get("max_pixels", 8000)
    if threads is None:
        threads = cfg.get("threads", 1)
    out: dict[int, tuple[str, str]] = {}
    todo = []
    for n in page_numbers:
        hit = _cache_read(cache, n)
        if hit is None:
            todo.append(n)
        else:
            out[n] = hit
    engine = ocr_engine()
    if engine is None or not todo:
        return out
    with tempfile.TemporaryDirectory(prefix="scgeo-ocr-") as tmp:
        if engine == "ocrmypdf":
            dest = Path(tmp) / "ocr.pdf"
            try:
                subprocess.run(["ocrmypdf", "--skip-text", "--output-type", "pdf", "--optimize", "0", "-l", language,
                                "--tesseract-timeout", str(timeout), "--max-image-mpixels", "0", "--quiet",
                                str(path), str(dest)], capture_output=True, timeout=timeout * 4, check=True)
                for n in list(todo):
                    out[n] = (page_text(dest, n), page_text(dest, n, layout=False))
                    _cache_write(cache, n, *out[n])
                    todo.remove(n)
            except (RuntimeError, OSError, subprocess.SubprocessError) as err:
                if log:
                    log(f"ocrmypdf failed ({type(err).__name__}); OCRing page by page")
            if not todo or not (shutil.which("tesseract") and shutil.which("pdftoppm")):
                return out
        for n in todo:
            try:
                out[n] = ocr_page(path, n, Path(tmp), language=language, timeout=timeout, dpi=dpi,
                                  max_pixels=max_pixels, threads=threads)
            except (RuntimeError, OSError, subprocess.SubprocessError) as err:
                if log:
                    log(f"OCR failed on page {n}: {type(err).__name__}")
                continue
            _cache_write(cache, n, *out[n])
    return out


# --- documents ----------------------------------------------------------------

def extract(path: Path, ocr: OcrFn | str | None = "auto", min_chars: int = 25,
            ocr_cache: Path | None = None) -> list[dict]:
    """One dict per page: file_page, text (layout), raw (reading order), method, needs_ocr.

    With ocr_cache (e.g. .cache/ocr), OCRed pages are kept in <ocr_cache>/<sha256 of the
    file>/p<N>.txt and reused, so a rerun only OCRs the pages that are still missing.
    """
    path = Path(path)
    pages = []
    for n in range(1, page_count(path) + 1):
        text = page_text(path, n)
        ok = has_text(text, min_chars)
        pages.append({"file_page": n, "text": text, "raw": page_text(path, n, layout=False) if ok else "",
                      "method": "pdf_text" if ok else "none", "needs_ocr": not ok})
    todo = [p["file_page"] for p in pages if p["needs_ocr"]]
    if todo and ocr is not None:
        cache = Path(ocr_cache) / sha256(path) if ocr_cache is not None else None
        done = {n: hit for n in todo if (hit := _cache_read(cache, n)) is not None}
        rest = [n for n in todo if n not in done]
        if rest:
            fn: OcrFn = (lambda p, ns: ocr_pages(p, ns, cache=cache)) if ocr == "auto" else ocr
            try:
                new = fn(path, rest)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                new = {}  # a custom OCR function that fails as a whole; ocr_pages itself never raises per page
            for n, (layout, raw) in new.items():
                if n in rest:
                    _cache_write(cache, n, layout, raw)
                    done[n] = (layout, raw)
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


def document(source_id: str, files: list[dict], ocr: OcrFn | str | None = "auto", min_chars: int = 25,
             ocr_cache: Path | None = None) -> dict:
    """Text for a whole document. Pages are numbered 1..N across all its files in order."""
    doc = {"source_id": source_id, "files": [], "pages": []}
    for i, f in enumerate(files):
        pages = extract(Path(f["path"]), ocr=ocr, min_chars=min_chars, ocr_cache=ocr_cache)
        doc["files"].append({"url": f.get("url"), "path": str(f["path"]), "sha256": sha256(Path(f["path"])),
                             "pages": len(pages), "first_page": len(doc["pages"]) + 1, "via": f.get("via")})
        for p in pages:
            doc["pages"].append({"page": len(doc["pages"]) + 1, "file": i, **p})
    return doc
