"""Find, download and read the full text of every catalog record.

For each record in data/catalog/sc_catalog.json, look for LEGAL open full
text, in this order:

* PDF links already in the catalog (from NGMDB product pages);
* the USGS Publications Warehouse (pubs.usgs.gov): publisher links on the
  NGMDB page, USGS DOIs (10.3133/...), or an exact title + year search for
  USGS records; its Document/Plate/Chapter PDFs, or PDFs on its index page;
* Unpaywall for other DOIs (open-access copies only), when CONTACT_EMAIL is
  set; the email is never logged or written to disk;
* for a record whose GIS is merged (merge.build), the map-sheet PDFs inside
  its GeMS package, taken from merge.build's cache (.cache/sources/<id>.zip;
  downloaded there once if missing, so neither job fetches it twice). The
  GIS files themselves are never read as text;
* NGMDB scanned map sheets (download.pl, screen- or print-optimized PDF),
  used only when nothing above was found;
* SCDNR FTP zips (PDFs inside them), last; GIS shapefile zips (*_poly.zip,
  *_line.zip) are never text candidates.

No shadow libraries. Records with no open full text are listed with their
metadata in data/review/needs_access.json for library access.

Records are processed Charleston County first, then the rest of the Coastal
Plain, then everything else (config/extract.json). PDFs go to
.cache/pdfs/<id>/, page text (with OCR where there is no text layer) to
.cache/text/<id>.json, OCRed pages one by one to .cache/ocr/<sha256>/, and one
checkpoint per document to .checkpoints/pdfs, so a rerun skips finished work.
A file counts as unread only when none of its pages has text; pages whose OCR
failed are listed as `ocr_missing_pages` and retried (from the OCR cache) up to
config "ocr.max_attempts" times.

    python -m harvest.pdfs [--limit N] [--max-minutes M] [--resolve-only] [--id ngmdb:10009 ...]
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from harvest import ngmdb_images, openaccess
from harvest.catalog import excluded_ids
from harvest.sgmc import _contact_headers

ROOT = Path(__file__).resolve().parent.parent
NGMDB = "https://ngmdb.usgs.gov"
PUBS_API = "https://pubs.usgs.gov/pubs-services/publication/"
UNPAYWALL = "https://api.unpaywall.org/v2/"
CONFIG: dict = json.loads((ROOT / "config" / "extract.json").read_text())
DONE = {"text", "needs_access"}
RESOLVER_VERSION = 5  # bump when resolve() finds new kinds of sources; unread records are resolved again
VIA_ORDER = ["catalog_pdf", "pubs_usgs", "publisher_pdf", "unpaywall", "openalex", "crossref_oa", "pubs_index", "gis_package", "ngmdb_scan", "ngmdb_image", "scgs_ftp"]


def safe_id(source_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", source_id)


def redact(text: str, email: str | None = None) -> str:
    email = email if email is not None else os.environ.get("CONTACT_EMAIL", "").strip()
    if not email:
        return text
    for form in (email, urllib.parse.quote(email), urllib.parse.quote_plus(email)):
        text = text.replace(form, "<CONTACT_EMAIL>")
    return text


# --- ordering ---------------------------------------------------------------

def merged_ids(catalog: list[dict]) -> set[str]:
    from merge.build import source_list

    return {s["id"] for s in source_list(catalog)}


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap(a, b) -> float:
    return _area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def in_coastal_plain(bbox, cfg: dict = CONFIG) -> bool:
    """True when the bbox centre lies south-east of the Fall Line polyline."""
    x, y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    line = cfg["coastal_plain"]["fall_line"]
    if x <= line[0][0]:
        seg = (line[0], line[1])
    elif x >= line[-1][0]:
        seg = (line[-2], line[-1])
    else:
        seg = next((a, b) for a, b in zip(line, line[1:]) if a[0] <= x <= b[0])
    (x0, y0), (x1, y1) = seg
    y_line = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return y < y_line


def tier(rec: dict, pilot_bbox, cfg: dict = CONFIG) -> int:
    b = rec.get("bbox")
    if not b:
        return 2
    ov = _overlap(b, pilot_bbox)
    if ov > 0:
        rules = cfg["pilot_overlap"]
        area = _area(b) or 1e-9
        if area <= rules["max_area_ratio"] * _area(pilot_bbox) or ov / area >= rules["min_share_inside"]:
            return 0
    return 1 if in_coastal_plain(b, cfg) else 2


_GEOLOGY = re.compile(r"geolog|stratigra|aquifer|hydrogeolog|subsurface|fault|seismic|formation|corehole|"
                      r"well|boring|sediment|quadrangle|phosphate|terrace|mineral", re.I)


def relevance(rec: dict) -> int:
    """0 for geologic maps and geology reports (NGMDB themes or title words), 1 otherwise."""
    return 0 if rec.get("themes") or _GEOLOGY.search(rec.get("title") or "") else 1


def queue(catalog: list[dict], pilot_bbox=None, cfg: dict = CONFIG, exclude: set[str] | None = None) -> list[dict]:
    """Records not excluded, in processing order: tier, geology first, smaller area, newer, id.

    Records whose GIS is merged are queued too: their map sheets and reports are read for unit
    descriptions, explanations, cross sections and references."""
    if pilot_bbox is None:
        pilot_bbox = json.loads((ROOT / "config" / "pilot_area.json").read_text())["bbox"]
    skip = excluded_ids() if exclude is None else set(exclude)
    out = []
    for r in catalog:
        if r["id"] in skip:
            continue
        out.append({**r, "_tier": tier(r, pilot_bbox, cfg)})
    return sorted(out, key=lambda r: (r["_tier"], relevance(r), _area(r["bbox"]) if r.get("bbox") else 1e9,
                                      -(int(r["year"]) if str(r.get("year") or "").isdigit() else 0), r["id"]))


# --- fetching ---------------------------------------------------------------

class HttpFetcher:
    """urllib with retries, the project User-Agent, a pause between requests and a size cap."""

    def __init__(self, cfg: dict = CONFIG):
        self.cfg = cfg
        self.ftp_down = False
        self._lock = threading.Lock()

    def _open(self, url: str, timeout: float):
        req = urllib.request.Request(url, headers=_contact_headers())
        return urllib.request.urlopen(req, timeout=timeout)

    def _retry(self, fn, url: str, tries: int = 3):
        is_ftp = url.startswith("ftp://")
        if is_ftp and self.ftp_down:
            raise OSError("FTP host unreachable earlier in this run")
        for attempt in range(1 if is_ftp else tries):
            try:
                out = fn()
                time.sleep(self.cfg["request_pause_seconds"])
                return out
            except urllib.error.HTTPError as err:
                if err.code in (403, 404, 410, 422) or attempt == tries - 1:
                    raise OSError(f"HTTP Error {err.code}") from None
            except (OSError, ValueError):
                if is_ftp:
                    self.ftp_down = True
                if is_ftp or attempt == tries - 1:
                    raise
            time.sleep(2 ** (attempt + 1))
        raise OSError("unreachable")

    def text(self, url: str) -> str:
        def go():
            with self._open(url, self.cfg["timeout_seconds"]) as r:
                return r.read().decode("utf-8", "replace")
        return self._retry(go, url)

    def bytes(self, url: str) -> bytes:
        def go():
            with self._open(url, self.cfg["timeout_seconds"]) as r:
                return r.read()
        return self._retry(go, url)

    def json(self, url: str):
        return json.loads(self.text(url))

    def download(self, url: str, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        cap = self.cfg["max_pdf_mb"] * 1_000_000
        timeout = self.cfg["ftp_timeout_seconds"] if url.startswith("ftp://") else self.cfg["timeout_seconds"]

        def go():
            with self._open(url, timeout) as r, open(tmp, "wb") as f:
                size = int(r.headers.get("Content-Length") or 0)
                if size > cap:
                    raise ValueError(f"file is {size // 1_000_000} MB, over the {cap // 1_000_000} MB cap")
                n = 0
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    n += len(chunk)
                    if n > cap:
                        raise ValueError("file over the size cap")
                    f.write(chunk)
            tmp.replace(dest)
            return dest
        try:
            return self._retry(go, url)
        finally:
            tmp.unlink(missing_ok=True)


# --- resolving --------------------------------------------------------------

_HOLDINGS = re.compile(r"var holdings\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)


def ngmdb_scans(page: str, formats=(2, 3)) -> list[str]:
    """download.pl URLs for each scanned sheet, preferring the first available format."""
    m = _HOLDINGS.search(page or "")
    if not m:
        return []
    try:
        h = json.loads(m.group(1))
    except ValueError:
        return []
    out = []
    for img in h.get("images", []):
        have = {int(d["fmt"]) for d in img.get("downloads", []) if str(d.get("fmt")).isdigit()}
        fmt = next((f for f in formats if f in have), None)
        if fmt is not None:
            out.append(f"{NGMDB}/ngm-bin/pdp/download.pl?q={img['item']}_{h['publication']}_{fmt}")
    return out


def publisher_links(page: str) -> list[str]:
    """Publisher URLs NGMDB lists under Other Resources (count_pub_refs.pl?url=...)."""
    out = []
    for q in re.findall(r"count_pub_refs\.pl\?([^\"'>\s]+)", page or ""):
        url = (urllib.parse.parse_qs(htmllib.unescape(q)).get("url") or [None])[0]
        if url and url.startswith("http") and url not in out and re.search(r"\.pdf$|/publication/|doi\.org/", url, re.I):
            out.append(url)
    return out


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _is_usgs(rec: dict) -> bool:
    return (rec.get("publisher") or "").strip() in ("U.S. Geological Survey", "USGS")


def _pubs_pdfs(index_id: str, fetcher, log) -> tuple[list[dict], list[str], int]:
    """(PDF candidates, index pages, number of Plate PDFs) for one Publications Warehouse record."""
    try:
        d = fetcher.json(PUBS_API + urllib.parse.quote(index_id))
    except (OSError, ValueError) as err:
        log(f"  pubs {index_id}: {type(err).__name__}: {redact(str(err))}")
        return [], [], 0
    pdfs, index_pages, plates = [], [], 0
    for link in d.get("links", []):
        kind, url = (link.get("type") or {}).get("text", ""), link.get("url") or ""
        is_pdf = url.lower().endswith(".pdf") or ((link.get("linkFileType") or {}).get("text") == "pdf")
        if kind in ("Document", "Plate", "Chapter") and is_pdf:
            pdfs.append({"url": url, "via": "pubs_usgs"})
            plates += kind == "Plate"
        elif kind == "Index Page" and "pubs.usgs.gov" in url:
            index_pages.append(url)
    return pdfs, index_pages, plates


def _index_page_pdfs(url: str, fetcher, log) -> list[dict]:
    try:
        page = fetcher.text(url)
    except OSError as err:
        log(f"  index page failed: {type(err).__name__}")
        return []
    base = url if url.endswith("/") else url + "/"
    out = []
    for href in re.findall(r"href\s*=\s*[\"']\s*([^\"']+?\.pdf)\s*[\"']", page, re.I):
        full = urllib.parse.urljoin(base, htmllib.unescape(href))
        if full.startswith(base) and {"url": full, "via": "pubs_index"} not in out:
            out.append({"url": full, "via": "pubs_index"})
    return out


def _pubs_search(rec: dict, fetcher, log) -> str | None:
    q = urllib.parse.urlencode({"title": rec.get("title") or "", "page_size": 10})
    try:
        d = fetcher.json(f"{PUBS_API}?{q}")
    except (OSError, ValueError) as err:
        log(f"  pubs search failed: {type(err).__name__}")
        return None
    want, year = _norm_title(rec.get("title")), str(rec.get("year") or "")
    for r in d.get("records", []):
        if _norm_title(r.get("title")) == want and (not year or str(r.get("publicationYear") or "") == year):
            return r.get("indexId")
    return None


def _doi(rec: dict) -> str | None:
    d = (rec.get("availability") or {}).get("doi") or ""
    m = re.search(r"(10\.\d{4,9}/\S+)", d)
    return m.group(1) if m else None


_GIS_ZIP = re.compile(r"_(?:poly|line|point|pts)\.zip$", re.I)


def gis_package_pdfs(rec: dict, fetcher, gis_cache: Path, log: Callable[..., None] = lambda *a: None) -> list[str]:
    """PDF members of the record's GeMS package in merge.build's cache, downloading it there once if missing."""
    url = (rec.get("availability") or {}).get("gems_download")
    if not url:
        return []
    path = Path(gis_cache) / f"{safe_id(rec['id'])}.zip"
    if not (path.exists() and zipfile.is_zipfile(path)):
        tmp = path.with_name(path.name + ".part")
        try:
            fetcher.download(url, tmp)
            if not zipfile.is_zipfile(tmp):
                raise OSError("GIS package is not a zip file")
            tmp.replace(path)
        except (OSError, ValueError) as err:
            tmp.unlink(missing_ok=True)
            log(f"  {rec['id']}: GIS package failed: {type(err).__name__}")
            return []
    with zipfile.ZipFile(path) as zf:
        return [m for m in zf.namelist() if m.lower().endswith(".pdf")]


def resolve(rec: dict, fetcher, email: str | None = None, log: Callable[..., None] = lambda *a: None,
            cfg: dict = CONFIG, api_cache: Path | None = None, gis_cache: Path | None = None) -> dict:
    """Candidate full-text URLs for one record and which sources were checked."""
    cands: list[dict] = []
    checked: list[str] = ["catalog"]

    def add(c: dict) -> None:
        if c["url"] not in {x["url"] for x in cands}:
            cands.append(c)

    for url in rec.get("availability", {}).get("pdf", []):
        add({"url": url, "via": "catalog_pdf"})

    page, scans, pub_links = "", [], []
    if rec.get("ngmdb_url"):
        checked.append("ngmdb")
        try:
            page = fetcher.text(rec["ngmdb_url"])
        except OSError as err:
            log(f"  {rec['id']}: NGMDB page failed: {type(err).__name__}")
            checked.remove("ngmdb")
        scans = ngmdb_scans(page, cfg["ngmdb_scan_formats"])
        pub_links = publisher_links(page)

    index_ids = []
    for url in pub_links:
        m = re.match(r"https?://pubs\.(?:er\.)?usgs\.gov/publication/([^/?#]+)", url)
        if m:
            index_ids.append(m.group(1))
        elif url.lower().endswith(".pdf"):
            add({"url": url, "via": "publisher_pdf"})
    doi = _doi(rec)
    if doi and doi.lower().startswith("10.3133/"):
        index_ids.append(doi.split("/", 1)[1])
    if not index_ids and _is_usgs(rec) and rec.get("title"):
        found = _pubs_search(rec, fetcher, log)
        if found:
            index_ids.append(found)
    if _is_usgs(rec) or index_ids:
        checked.append("pubs_usgs")
    plates = 0
    for iid in dict.fromkeys(index_ids):
        pdfs, index_pages, n_plates = _pubs_pdfs(iid, fetcher, log)
        plates += n_plates
        for c in pdfs:
            add(c)
        if not pdfs:
            for url in index_pages:
                for c in _index_page_pdfs(url, fetcher, log):
                    add(c)

    api_cache = api_cache if api_cache is not None else openaccess.CACHE
    if doi and not doi.lower().startswith("10.3133/"):
        checked += ["unpaywall" if email else "unpaywall_skipped", "openalex"]
        for c in openaccess.open_copies(doi, None, fetcher, email, api_cache, log):
            add(c)

    # Crossref: find (or confirm) a DOI for records still without open text, then
    # look for legal open copies of it (or the USGS Publications Warehouse for 10.3133).
    crossref = None
    if not cands and cfg.get("crossref", {}).get("enabled", True) and rec.get("title"):
        checked.append("crossref")
        crossref = openaccess.lookup(rec, fetcher, email, api_cache)
        found = crossref.get("doi") if crossref.get("status") == "match" else None
        if found and doi:
            crossref["confirms_catalog_doi"] = found.lower() == doi.lower()
        if found and found.lower().startswith("10.3133/"):
            pdfs, index_pages, n_plates = _pubs_pdfs(found.split("/", 1)[1], fetcher, log)
            plates += n_plates
            for c in pdfs:
                add(c)
            for url in ([] if pdfs else index_pages):
                for c in _index_page_pdfs(url, fetcher, log):
                    add(c)
        elif found and (not doi or found.lower() != doi.lower()):
            for v in ("unpaywall" if email else "unpaywall_skipped", "openalex"):
                if v not in checked:
                    checked.append(v)
            for c in openaccess.open_copies(found, crossref, fetcher, email, api_cache, log):
                add(c)

    # A merged GIS record's map sheets inside its GeMS package (from merge.build's cache).
    if not cands and gis_cache is not None and (rec.get("availability") or {}).get("gems_download"):
        checked.append("gis_package")
        members = gis_package_pdfs(rec, fetcher, gis_cache, log)
        if members:
            add({"url": rec["availability"]["gems_download"], "via": "gis_package", "members": members,
                 "path": str(Path(gis_cache) / f"{safe_id(rec['id'])}.zip")})

    # Scanned sheets only when nothing else was found, or for a map whose Warehouse
    # entry has a text Document (often just a cover) but no Plate.
    map_without_plates = (rec.get("kind") == "map" and not plates and cands
                          and all(c["via"] == "pubs_usgs" for c in cands))
    if not cands or map_without_plates:
        for url in scans:
            add({"url": url, "via": "ngmdb_scan"})
    images = cfg.get("ngmdb_images", {})
    if not cands and images.get("enabled") and (rec.get("publisher") or "").strip() in images.get("publishers", []):
        # Browse images (Zoomify tiles) of sheets with no PDF: OCRed into page text.
        for url in ngmdb_images.browse_images(page, images.get("providers", [])):
            add({"url": url, "via": "ngmdb_image"})
    if not cands:
        for url in rec.get("availability", {}).get("scgs_ftp", []):
            if not _GIS_ZIP.search(url):  # GIS shapefile packages hold no text to read
                add({"url": url, "via": "scgs_ftp"})
    cands.sort(key=lambda c: VIA_ORDER.index(c["via"]))
    out = {"candidates": cands[: cfg["max_files_per_document"]], "checked": checked}
    if crossref is not None:
        out["crossref"] = {k: v for k, v in crossref.items() if k not in ("license", "link")} | (
            {"license": [l["URL"] for l in crossref.get("license") or []]} if crossref.get("license") else {})
    return out


# --- processing ---------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def _is_pdf(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(1024).lstrip()[:5] == b"%PDF-"


def download_files(rec: dict, cands: list[dict], fetcher, pdf_dir: Path, log) -> tuple[list[dict], list[str]]:
    files, problems = [], []
    for i, c in enumerate(cands, 1):
        try:
            if c["via"] == "ngmdb_image":
                dest = pdf_dir / f"{i:02d}.pdf"
                if not dest.exists():
                    opts = CONFIG.get("ngmdb_images", {})
                    ngmdb_images.build_pdf(c["url"], dest, fetcher, tier_offset=opts.get("tier_offset", 0),
                                           workers=opts.get("tile_workers", 4))
                files.append({"url": c["url"], "via": c["via"], "path": str(dest), "bytes": dest.stat().st_size})
                continue
            if c["via"] == "gis_package":
                zpath = Path(c["path"])
                if not (zpath.exists() and zipfile.is_zipfile(zpath)):  # merge cache cleared: fetch it again once
                    gis_package_pdfs(rec, fetcher, zpath.parent, log)
                with zipfile.ZipFile(zpath) as zf:
                    for j, m in enumerate(c["members"], 1):
                        dest = pdf_dir / f"{i:02d}-{j:02d}.pdf"
                        if not dest.exists():
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(m) as src, open(dest, "wb") as out:
                                shutil.copyfileobj(src, out)
                        files.append({"url": c["url"], "member": m, "via": c["via"], "path": str(dest)})
                continue  # the package stays in merge.build's cache
            if c["url"].lower().endswith(".zip"):
                zpath = fetcher.download(c["url"], pdf_dir / f"{i:02d}.zip")
                with zipfile.ZipFile(zpath) as zf:
                    members = [m for m in zf.namelist() if m.lower().endswith(".pdf")]
                    for j, m in enumerate(members, 1):
                        dest = pdf_dir / f"{i:02d}-{j:02d}.pdf"
                        with zf.open(m) as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out)
                        files.append({"url": c["url"], "member": m, "via": c["via"], "path": str(dest)})
                zpath.unlink(missing_ok=True)
                if not members:
                    problems.append(f"{c['via']}: zip has no PDF")
                continue
            dest = pdf_dir / f"{i:02d}.pdf"
            if not dest.exists():
                fetcher.download(c["url"], dest)
            if not _is_pdf(dest):
                dest.unlink()
                problems.append(f"{c['via']}: not a PDF (landing or login page)")
                continue
            files.append({"url": c["url"], "via": c["via"], "path": str(dest), "bytes": dest.stat().st_size})
        except (OSError, ValueError, zipfile.BadZipFile) as err:
            problems.append(f"{c['via']}: {type(err).__name__}: {redact(str(err))[:200]}")
            log(f"  {rec['id']}: download failed ({c['via']}): {type(err).__name__}")
    return files, problems


def text_summary(doc: dict) -> dict:
    from extract import packets, triage

    n = len(doc["pages"])
    kinds = Counter()
    kept_chars = 0
    for p in doc["pages"]:
        t = triage.classify(p.get("text", ""), p["page"], n, method=p.get("method", "pdf_text"))
        kinds[t["kind"]] += 1
        if t["keep"]:
            kept_chars += len(packets.compact(p["text"]))
    return {"pages": n, "pages_by_method": dict(Counter(p["method"] for p in doc["pages"])),
            "pages_by_kind": dict(kinds), "kept_chars": kept_chars,
            "estimated_tokens": int(kept_chars / CONFIG["chars_per_token"])}


def _stale(ck: dict, email: str | None) -> bool:
    """True when a record's sources should be looked up (again)."""
    if "candidates" not in ck:
        return True
    if email and "unpaywall_skipped" in ck.get("checked", []):
        return True
    return ck.get("status") != "text" and ck.get("resolver_version") != RESOLVER_VERSION


def _ocr_retry_due(ck: dict, ocr) -> bool:
    """True when a document still has pages without text that OCR should try again.

    Finished pages come from the OCR cache, so a retry only redoes the missing ones; after
    CONFIG["ocr"]["max_attempts"] tries the document is left as it is.
    """
    from extract import pdftext

    if ocr is None or ck.get("status") not in ("needs_ocr", "text"):
        return False
    if ck["status"] == "text" and not ck.get("ocr_missing_pages"):
        return False
    if ck.get("ocr_attempts", 0) >= CONFIG["ocr"].get("max_attempts", 3):
        return False
    return pdftext.ocr_engine() is not None


def process(rec: dict, fetcher, ckpt_dir: Path, cache_dir: Path, email: str | None, ocr="auto",
            resolve_only: bool = False, log: Callable[..., None] = print, drop_pdfs: bool = False) -> dict:
    """Run the remaining stages for one record; returns its checkpoint.

    With drop_pdfs, a document's PDFs are deleted once its text is read (CI keeps only text in its cache).
    """
    from extract import pdftext

    sid = safe_id(rec["id"])
    path = Path(ckpt_dir) / f"{sid}.json"
    ck = _load(path) or {"id": rec["id"]}
    ck.update(tier=rec.get("_tier"), kind=rec.get("kind"))
    if _stale(ck, email):
        r = resolve(rec, fetcher, email=email, log=log, api_cache=Path(cache_dir) / "api",
                    gis_cache=Path(cache_dir) / "sources")
        ck.pop("crossref", None)
        ck.update(r, resolved_at=_now(), resolver_version=RESOLVER_VERSION)
        ck.pop("files", None)
        ck["status"] = "resolved" if r["candidates"] else "needs_access"
        ck["reason"] = None if r["candidates"] else "no open full text found"
        _save(path, ck)
    if resolve_only or not ck["candidates"]:
        return ck

    pdf_dir = Path(cache_dir) / "pdfs" / sid
    text_path = Path(cache_dir) / "text" / f"{sid}.json"
    files_ok = ck.get("files") and all(Path(f["path"]).exists() for f in ck["files"])
    if not files_ok:
        files, problems = download_files(rec, ck["candidates"], fetcher, pdf_dir, log)
        ck.update(files=files, problems=problems, downloaded_at=_now())
        ck.pop("ocr_attempts", None)
        if files:
            ck["status"] = "downloaded"
        elif problems and all("not a PDF" in p or "no PDF" in p or "HTTP Error 4" in p for p in problems):
            ck.update(status="needs_access", reason="; ".join(problems))
        else:
            ck.update(status="failed", reason="; ".join(problems))
        _save(path, ck)
        if not files:
            return ck

    redo_ocr = _ocr_retry_due(ck, ocr)
    if not text_path.exists() or ck.get("status") == "downloaded" or redo_ocr:
        try:
            doc = pdftext.document(rec["id"], ck["files"], ocr=ocr, min_chars=CONFIG["min_text_chars_per_page"],
                                   ocr_cache=Path(cache_dir) / "ocr")
        except (RuntimeError, OSError) as err:
            ck.update(status="failed", reason=f"text: {type(err).__name__}: {str(err)[:200]}")
            _save(path, ck)
            return ck
        doc["record"] = {k: rec.get(k) for k in ("id", "title", "citation", "year", "scale", "publisher", "kind")}
        _save(text_path, doc)
        summary = text_summary(doc)
        # A file with no text on any page is a scanned sheet or report: reading the
        # rest without it would give an incomplete extraction, so wait for OCR.
        unread = [f["url"] for i, f in enumerate(doc["files"])
                  if all(p["method"] == "none" for p in doc["pages"] if p["file"] == i)]
        ck.update(summary, unread_files=len(unread), text_at=_now(),
                  text_path=str(text_path.relative_to(cache_dir.parent))
                  if cache_dir.parent in text_path.parents else str(text_path))
        # Pages that needed OCR (no text layer) and those still without text. A file with
        # some text is read now; its missing pages are retried later from the OCR cache.
        needed = [p["page"] for p in doc["pages"] if p["method"] != "pdf_text"]
        missing = [p["page"] for p in doc["pages"] if p.get("needs_ocr")]
        attempted = bool(needed) and ocr is not None and pdftext.ocr_engine() is not None
        if attempted:
            ck["ocr_attempts"] = ck.get("ocr_attempts", 0) + 1
        ck["ocr_missing_pages"] = missing
        ck["status"] = "needs_ocr" if unread else "text"
        if not missing:
            ck["reason"] = None
        elif attempted:
            ck["reason"] = f"OCR failed on {len(missing)} of {len(needed)} pages"
            if unread:
                ck["reason"] += f"; {len(unread)} file(s) have no text yet"
        elif ocr is None:
            ck["reason"] = f"OCR was not run; {len(missing)} page(s) without a text layer"
        else:
            ck["reason"] = (f"no OCR engine was available; {len(unread)} file(s) are scans without a text layer"
                            if unread else f"no OCR engine was available; {len(missing)} page(s) without a text layer")
        if drop_pdfs and ck["status"] == "text" and not _ocr_retry_due(ck, ocr):
            shutil.rmtree(pdf_dir, ignore_errors=True)
            ck["pdfs_dropped"] = True
        _save(path, ck)
    return ck


# --- run ----------------------------------------------------------------------

_META = ("id", "title", "authors", "year", "publisher", "series", "series_key", "scale", "kind", "citation",
         "ngmdb_url")


def write_needs_access(ordered: list[dict], cks: dict[str, dict], review_dir: Path, drop: set[str] = frozenset()) -> int:
    review_dir = Path(review_dir)
    path = review_dir / "needs_access.json"
    old = {r["id"]: r for r in (_load(path) or {}).get("records", [])}
    out = []
    for rec in ordered:
        ck = cks.get(rec["id"])
        if ck is None:
            if rec["id"] in old:
                out.append(old.pop(rec["id"]))
            continue
        old.pop(rec["id"], None)
        if ck.get("status") != "needs_access":
            continue
        out.append({**{k: rec.get(k) for k in _META}, "doi": (rec.get("availability") or {}).get("doi"),
                    "tier": rec.get("_tier"), "checked": ck.get("checked", []), "reason": ck.get("reason"),
                    **({"crossref": ck["crossref"]} if ck.get("crossref") else {})})
    out += [old[k] for k in sorted(old) if k not in drop]  # drop: records now excluded
    review_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "about": "Catalog records with no legal open full text found. Metadata only; for library access. "
                 "Written by harvest/pdfs.py.",
        "count": len(out), "records": out}, indent=1, ensure_ascii=False) + "\n")
    return len(out)


def status_counts(ordered: list[dict], cks: dict[str, dict]) -> dict:
    by_status, by_kind, by_via, by_tier = Counter(), Counter(), Counter(), Counter()
    tokens = pages = 0
    for rec in ordered:
        ck = cks.get(rec["id"])
        st = ck.get("status") if ck else "pending"
        by_status[st] += 1
        by_kind[f"{rec.get('kind')}:{'full_text' if ck and ck.get('candidates') else 'metadata_only' if ck else 'pending'}"] += 1
        by_tier[f"tier{rec.get('_tier')}:{st}"] += 1
        if ck and ck.get("candidates"):
            by_via[ck["candidates"][0]["via"]] += 1
        if ck:
            tokens += ck.get("estimated_tokens") or 0
            pages += ck.get("pages") or 0
    return {"queued": len(ordered), "by_status": dict(by_status), "by_kind": dict(sorted(by_kind.items())),
            "by_source": dict(by_via), "by_tier": dict(sorted(by_tier.items())),
            "with_text_pages": pages, "estimated_tokens_with_text": tokens}


def run(catalog_path: Path = ROOT / "data" / "catalog" / "sc_catalog.json",
        checkpoint_dir: Path = ROOT / ".checkpoints" / "pdfs", cache_dir: Path = ROOT / ".cache",
        review_dir: Path = ROOT / "data" / "review", pilot_bbox=None, fetcher=None, ocr="auto",
        log: Callable[..., None] = print, limit: int | None = None, max_minutes: float | None = None,
        resolve_only: bool = False, ids: list[str] | None = None, workers: int | None = None,
        drop_pdfs: bool = False) -> dict:
    start = time.monotonic()
    deadline = None if max_minutes is None else start + max_minutes * 60
    catalog = json.loads(Path(catalog_path).read_text())
    ordered = queue(catalog, pilot_bbox)
    todo = [r for r in ordered if not ids or r["id"] in ids]
    fetcher = fetcher or HttpFetcher()
    email = os.environ.get("CONTACT_EMAIL", "").strip() or None
    checkpoint_dir, cache_dir = Path(checkpoint_dir), Path(cache_dir)
    safe_log = lambda msg: log(redact(str(msg), email or ""))

    def needs_work(rec: dict) -> bool:
        ck = _load(checkpoint_dir / f"{safe_id(rec['id'])}.json")
        if not ck or _stale(ck, email):
            return True
        st = ck.get("status")
        if resolve_only:
            return "candidates" not in ck
        if st == "needs_ocr" or (st == "text" and ck.get("ocr_missing_pages")):
            return _ocr_retry_due(ck, ocr)
        return st not in DONE

    work = [r for r in todo if needs_work(r)]
    if limit is not None:
        work = work[:limit]
    safe_log(f"queue: {len(ordered)} records; {len(work)} to process this run")
    done = 0
    lock = threading.Lock()

    def one(rec: dict) -> None:
        nonlocal done
        if deadline is not None and time.monotonic() >= deadline:
            return
        try:
            ck = process(rec, fetcher, checkpoint_dir, cache_dir, email, ocr=ocr, resolve_only=resolve_only,
                         log=safe_log, drop_pdfs=drop_pdfs)
            safe_log(f"{rec['id']} (tier {rec['_tier']}): {ck.get('status')}"
                     + (f", {ck.get('pages')} pages" if ck.get("pages") else ""))
        except Exception as err:  # keep going; the checkpoint lets the next run retry
            safe_log(f"{rec['id']}: {type(err).__name__}: {str(err)[:200]}")
        with lock:
            done += 1

    n_workers = workers or CONFIG["workers"]
    if n_workers <= 1:
        for rec in work:
            one(rec)
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            list(pool.map(one, work))

    cks = {r["id"]: ck for r in ordered if (ck := _load(checkpoint_dir / f"{safe_id(r['id'])}.json"))}
    n_need = write_needs_access(ordered, cks, review_dir, drop=excluded_ids())
    status = status_counts(ordered, cks) | {"processed_this_run": done, "needs_access_listed": n_need,
                                            "minutes": round((time.monotonic() - start) / 60, 1), "at": _now()}
    _save(checkpoint_dir / "status.json", status)
    safe_log(json.dumps(status, indent=1))
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="process at most N documents this run")
    parser.add_argument("--max-minutes", type=float, help="stop starting new documents after M minutes")
    parser.add_argument("--resolve-only", action="store_true", help="find full-text links but do not download")
    parser.add_argument("--id", action="append", dest="ids", help="only these catalog ids")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--drop-pdfs", action="store_true", help="delete each PDF once its text is read")
    args = parser.parse_args()
    run(limit=args.limit, max_minutes=args.max_minutes, resolve_only=args.resolve_only, ids=args.ids,
        workers=args.workers, ocr=None if args.no_ocr else "auto", drop_pdfs=args.drop_pdfs)


if __name__ == "__main__":
    main()
