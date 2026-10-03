"""Catalog of every published South Carolina geology map and report.

Merges four catalogs into one list of works, keeping where each fact came
from:

* USGS National Geologic Map Database (NGMDB): every product listed for SC,
  with bedrock/surficial themes and, from each product page, the citation,
  bounding box, keywords and download links (PDF, GIS, GeMS).
* SC Geological Survey 1:24,000 map index (ArcGIS service): the quadrangles
  each map covers, plus SCGS's table of which maps have GIS.
* SCDNR GIS FTP folder: quadrangle shapefiles.

Records found in more than one catalog are merged by publication number
(for example "SCGS GQM-5"). The job is resumable: product pages are cached
under the checkpoint directory and skipped on the next run.

    python -m harvest.catalog [--out data/catalog] [--checkpoints .checkpoints/catalog]
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from harvest.sgmc import _contact_headers
from model.provenance import ExtractionMethod, StoredValue

ROOT = Path(__file__).resolve().parent.parent
NGMDB = "https://ngmdb.usgs.gov"
SCGS_INDEX_URL = "https://services.arcgis.com/acgZYxoN5Oj8pDLa/arcgis/rest/services/24K_Quads/FeatureServer"
SCDNR_DIGITAL_DATA = "https://www.dnr.sc.gov/geology/digital-data.html"
THEMES = {"bedrock": "geolgenbed", "surficial": "geolgensur", "structural": "geolstruc", "engineering": "geoleng"}

# --- parsing ---------------------------------------------------------------

_SCGS_SERIES = [
    (r"\bGQM-?\s*(\d+)", "GQM"),
    (r"\bGeologic Quadrangle Map\s+(\d+)", "GQM"),
    (r"\bOFR-?\s*(\d+)", "OFR"),
    (r"\bOpen-File Report\s+(\d+)\b", "OFR"),
    (r"\bMS-?\s*(\d+)", "MS"),
    (r"\bMap Series\s+(\d+)", "MS"),
    (r"\bGGMS-?\s*(\d+)", "GGMS"),
    (r"\bBulletin\s+(\d+)", "B"),
]
_USGS_SERIES = [
    (r"\bOpen[- ]File Report\s+(?:OFR[\s-]*)?(\d{2,4}-\d+[A-Z]?)", "OFR"),
    (r"\bOFR?[\s-]*(\d{2,4}-\d+[A-Z]?)", "OFR"),
    (r"\b(I-\d+[A-Z-]*)", None),
    (r"\b(MF-\d+[A-Z-]*)", None),
    (r"\b(GQ-\d+)", None),
    (r"\bScientific Investigations Map\s+(\d+)", "SIM"),
    (r"\bSIM-?(\d+)", "SIM"),
    (r"\bProfessional Paper\s+(\d+[A-Z-]*)", "PP"),
    (r"\bBulletin\s+(\d+[A-Z-]*)", "B"),
    (r"\bScientific Investigations Report\s+(?:SIR-)?(\d{4}-\d+)", "SIR"),
    (r"\bWater-Resources Investigations Report\s+(\d+-\d+)", "WRIR"),
    (r"\bData Series\s+(\d+)", "DS"),
]


def _publisher_code(publisher: str | None) -> str | None:
    p = (publisher or "").strip()
    if p in ("SCGS", "South Carolina Geological Survey", "South Carolina Division of Geology"):
        return "SCGS"
    if p in ("USGS", "U.S. Geological Survey"):
        return "USGS"
    return None


def series_key(series: str | None, publisher: str | None) -> str | None:
    """Stable publication number such as 'SCGS GQM-5' or 'USGS I-1935'."""
    code = _publisher_code(publisher)
    s = (series or "").strip()
    if not s or not code:
        return None
    for pattern, prefix in (_SCGS_SERIES if code == "SCGS" else _USGS_SERIES):
        m = re.search(pattern, s)
        if m:
            return f"{code} {prefix}-{m.group(1)}" if prefix else f"{code} {m.group(1)}"
    return None


def scale_denominator(scale) -> int | None:
    if isinstance(scale, (int, float)):
        return int(scale) or None
    m = re.search(r"(?:1:)?\s*([\d,]{3,})", str(scale or ""))
    return int(m.group(1).replace(",", "")) if m else None


def parse_product_page(page: str) -> dict:
    """Citation, bounding box, keywords and download links from an NGMDB product page."""
    out = {"bbox": None, "citation": None, "keywords": [], "downloads": {}}
    m = re.search(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', page, re.S)
    if m:
        try:
            ld = json.loads(m.group(1))
        except ValueError:
            ld = {}
        out["citation"] = ld.get("citation")
        out["keywords"] = [k.strip() for k in (ld.get("keywords") or "").split(",") if k.strip()]
        box = ((ld.get("spatialCoverage") or {}).get("geo") or {}).get("box")
        if box:
            (s, w), (n, e) = [map(float, part.split()) for part in box.split(",")]
            out["bbox"] = [w, s, e, n]
    downloads: dict[str, list[str]] = defaultdict(list)
    for href in re.findall(r'href="([^"]+)"', page):
        url = urllib.parse.urljoin(NGMDB + "/", htmllib.unescape(href))
        if "gems_download.pl" in url:
            kind = "gems"
        elif re.search(r"gis_download|\.zip$|\.gdb", url, re.I):
            kind = "gis"
        elif re.search(r"\.pdf$", url, re.I):
            kind = "pdf"
        elif re.search(r"\.tif+$|\.kmz$", url, re.I):
            kind = "image"
        elif re.match(r"https?://(dx\.)?doi\.org/10\.", url):
            kind = "doi"
        else:
            continue
        if url not in downloads[kind]:
            downloads[kind].append(url)
    out["downloads"] = dict(downloads)
    return out


# --- building ---------------------------------------------------------------

def _clean(v) -> str:
    return re.sub(r"[\x00-\x1f]", "", str(v or "")).strip()


def _prov(source_id: str, locator: str, retrieved_at: str) -> dict:
    v = StoredValue(value=None, source_id=source_id, page=None, locator=locator,
                    extraction_method=ExtractionMethod.CATALOG_IMPORT, confidence=1.0)
    return {k: v.to_dict()[k] for k in ("source_id", "locator", "extraction_method", "confidence")} | {
        "retrieved_at": retrieved_at}


def _scgs_index_key(row: dict) -> str | None:
    """Publication number for an SCGS index row, tolerating its mixed formats."""
    pub, series = _clean(row.get("Pub_1")), _clean(row.get("Series"))
    if not pub or pub.lower() in ("draft", "0", "1") or "XX" in pub:
        return None
    if re.match(r"EQM-\d+$", pub):
        return f"EDMAP {pub}"
    usgs = "USGS" in series or re.match(r"(I|MF|GQ)-", pub) or re.search(r"\d{2,4}-\d+", pub)
    if usgs:
        return series_key(pub, "USGS") or series_key(f"{series} {pub}", "USGS")
    return series_key(pub, "SCGS") or series_key(f"{series} {pub}", "SCGS")


def _is_draft(row: dict) -> bool:
    return _clean(row.get("Pub_1")).lower() == "draft" or "XX" in _clean(row.get("Pub_1"))


def build_catalog(ngmdb_rows: Iterable[dict], themes: dict[str, set], pages: dict[int, dict],
                  scgs_index: Iterable[dict], scgs_gis: Iterable[dict], ftp_links: Iterable[str],
                  retrieved_at: str) -> list[dict]:
    records: dict[str, dict] = {}
    by_key: dict[str, dict] = {}

    for row in ngmdb_rows:
        pid = int(row["id"])
        page = pages.get(pid, {})
        key = series_key(row.get("series"), row.get("published_by"))
        dl = page.get("downloads", {})
        rec = {
            "id": f"ngmdb:{pid}",
            "title": _clean(row.get("title")),
            "authors": _clean(row.get("authors")),
            "year": row.get("year"),
            "publisher": _clean(row.get("published_by")),
            "series": _clean(row.get("series")),
            "series_key": key,
            "scale": scale_denominator(row.get("scale")),
            "themes": sorted(t for t, ids in themes.items() if pid in ids),
            "quadrangles": [],
            "bbox": page.get("bbox"),
            "citation": page.get("citation"),
            "keywords": page.get("keywords", []),
            "availability": {
                "online": str(row.get("online")) == "True",
                "gis": bool(row.get("gis")) or bool(dl.get("gems") or dl.get("gis")),
                "gems_download": (dl.get("gems") or [None])[0],
                "gis_download": (dl.get("gis") or [None])[0],
                "pdf": dl.get("pdf", []),
                "doi": (dl.get("doi") or [None])[0],
                "scgs_ftp": [],
            },
            "ngmdb_url": f"{NGMDB}/Prodesc/proddesc_{pid}.htm",
            "provenance": [_prov("ngmdb-catalog", f"proddesc_{pid}", retrieved_at)],
        }
        records[rec["id"]] = rec
        if key and key not in by_key:
            by_key[key] = rec

    # SCGS 1:24,000 index: one row per quadrangle; group by publication.
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in scgs_index:
        key = _scgs_index_key(row)
        if key:
            groups[key].append(row)
    for key, rows in groups.items():
        rec = by_key.get(key)
        if rec is None:
            first = rows[0]
            pub = _clean(first.get("Pub_1"))
            rec = {
                "id": f"scgs:{pub}",
                "title": _clean(first.get("Title")),
                "authors": _clean(first.get("Author")),
                "year": first.get("Map_Year") or first.get("Year") or None,
                "publisher": "U.S. Geological Survey" if key.startswith("USGS") else "South Carolina Geological Survey",
                "series": _clean(first.get("Series")),
                "series_key": key,
                "scale": scale_denominator(first.get("Scale")),
                "themes": [],
                "quadrangles": [],
                "bbox": None,
                "citation": None,
                "keywords": [],
                "availability": {"online": False, "gis": False, "gems_download": None, "gis_download": None,
                                 "pdf": [], "doi": None, "scgs_ftp": []},
                "ngmdb_url": None,
                "provenance": [],
            }
            records[rec["id"]] = rec
            by_key[key] = rec
        rec["quadrangles"] = sorted({_clean(r.get("QUADNAME")) for r in rows} | set(rec["quadrangles"]))
        rec["_tiles"] = sorted({_clean(r.get("TILE_NAME")).lower() for r in rows})
        rec["provenance"].append(_prov("scgs-24k-index", "OBJECTID=" + ",".join(
            str(r["OBJECTID"]) for r in rows), retrieved_at))

    for row in scgs_index:
        if not _is_draft(row):
            continue
        tile = _clean(row.get("TILE_NAME"))
        quad = _clean(row.get("QUADNAME"))
        rec = records.setdefault(f"scgs-draft:{tile}", {
            "id": f"scgs-draft:{tile}",
            "title": _clean(row.get("Title")) or f"Geologic map of the {quad.title()} quadrangle (in progress)",
            "authors": _clean(row.get("Author")),
            "year": None,
            "publisher": _clean(row.get("Mapped_By")) or "South Carolina Geological Survey",
            "series": "", "series_key": None,
            "scale": scale_denominator(row.get("Scale")),
            "themes": [], "quadrangles": [quad], "bbox": None, "citation": None, "keywords": [],
            "availability": {"online": False, "gis": False, "gems_download": None, "gis_download": None,
                             "pdf": [], "doi": None, "scgs_ftp": []},
            "ngmdb_url": None, "status": "draft", "provenance": [],
            "_tiles": [tile.lower()],
        })
        rec["provenance"].append(_prov("scgs-24k-index", f"OBJECTID={row['OBJECTID']}", retrieved_at))

    for row in scgs_gis:
        key = series_key(_clean(row.get("Pub_1")), "SCGS")
        rec = by_key.get(key)
        if rec is None:
            continue
        if _clean(row.get("GIS_Available")).lower() == "yes":
            rec["availability"]["gis"] = True
        rec["provenance"].append(_prov("scgs-24k-gis-table", f"Pub_1={_clean(row.get('Pub_1'))}", retrieved_at))

    ftp_by_tile: dict[str, list[str]] = defaultdict(list)
    for url in ftp_links:
        ftp_by_tile[url.rsplit("/", 1)[-1][:5].lower()].append(url)
    for rec in records.values():
        links = sorted({u for t in rec.pop("_tiles", []) for u in ftp_by_tile.get(t, [])})
        if links:
            rec["availability"]["scgs_ftp"] = links
            rec["availability"]["gis"] = True
            rec["provenance"].append(_prov("scdnr-ftp", ",".join(links), retrieved_at))

    for rec in records.values():
        rec.setdefault("status", "published")
        is_map = rec["themes"] or rec["quadrangles"] or re.search(r"\bmaps?\b", rec["title"], re.I)
        rec["kind"] = "map" if is_map else "publication"
    return sorted(records.values(), key=lambda r: (r["kind"], r["id"]))


def summarize(records: list[dict]) -> dict:
    themes = Counter(t for r in records for t in r["themes"])
    return {
        "records": len(records),
        "maps": sum(r["kind"] == "map" for r in records),
        "publications": sum(r["kind"] == "publication" for r in records),
        "drafts": sum(r["status"] == "draft" for r in records),
        "with_gis": sum(r["availability"]["gis"] for r in records),
        "with_gems": sum(bool(r["availability"]["gems_download"]) for r in records),
        "online": sum(r["availability"]["online"] for r in records),
        "by_theme": dict(sorted(themes.items())),
        "by_scale": dict(sorted(Counter(r["scale"] for r in records if r["scale"]).most_common(12))),
        "by_publisher": dict(Counter(r["publisher"] for r in records).most_common(12)),
    }


# --- fetching ---------------------------------------------------------------

def _get(url: str, params: dict | None = None, raw: bool = False, tries: int = 4):
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params, doseq=True)}"
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=_contact_headers())
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
            return body.decode("utf-8", "replace") if raw else json.loads(body)
        except (OSError, ValueError):
            if attempt == tries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def ngmdb_search(state: str = "SC", **filters) -> list[dict]:
    rows, start = [], 1
    while True:
        d = _get(f"{NGMDB}/ngm-bin/ngm_search_json.pl", {"State": state, "start": start, "range": 500, **filters})
        d = d["ngmdb_catalog_search"]
        rows += d["results"]
        if not d["results"] or len(rows) >= int(d["filter"]["total_count"]):
            return rows
        start += len(d["results"])


def arcgis_rows(layer_url: str) -> list[dict]:
    rows, offset = [], 0
    while True:
        j = _get(f"{layer_url}/query", {"where": "1=1", "outFields": "*", "returnGeometry": "false",
                                        "resultOffset": offset, "resultRecordCount": 1000, "f": "json"})
        feats = j.get("features", [])
        rows += [f["attributes"] for f in feats]
        if not j.get("exceededTransferLimit") or not feats:
            return rows
        offset += len(feats)


def product_pages(ids: Iterable[int], ckpt: Path, log: Callable[..., None], workers: int = 4) -> dict[int, dict]:
    """Parsed NGMDB product pages, cached per product so a rerun resumes."""
    from concurrent.futures import ThreadPoolExecutor

    ckpt.mkdir(parents=True, exist_ok=True)
    pages: dict[int, dict] = {}
    todo = []
    for pid in ids:
        f = ckpt / f"{pid}.json"
        if f.exists():
            pages[pid] = json.loads(f.read_text())
        else:
            todo.append(pid)
    log(f"  product pages: {len(pages)} cached, {len(todo)} to fetch")

    def fetch(pid: int):
        try:
            page = parse_product_page(_get(f"{NGMDB}/Prodesc/proddesc_{pid}.htm", raw=True))
        except OSError as err:
            log(f"product {pid} failed: {err}")
            return pid, None
        (ckpt / f"{pid}.json").write_text(json.dumps(page))
        return pid, page

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (pid, page) in enumerate(pool.map(fetch, todo), 1):
            if page is not None:
                pages[pid] = page
            if n % 200 == 0:
                log(f"  product pages: {n}/{len(todo)}")
    return pages


def run(out_dir: Path, checkpoint_dir: Path, log: Callable[..., None] = print) -> dict:
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = ngmdb_search()
    log(f"NGMDB: {len(rows)} SC products")
    themes = {name: {int(r["id"]) for r in ngmdb_search(geologictheme=code)} for name, code in THEMES.items()}
    pages = product_pages([int(r["id"]) for r in rows], Path(checkpoint_dir) / "ngmdb", log)
    scgs_index = arcgis_rows(f"{SCGS_INDEX_URL}/0")
    scgs_gis = arcgis_rows(f"{SCGS_INDEX_URL}/1")
    ftp = sorted(set(re.findall(r"ftp://ftpdata\.dnr\.sc\.gov/[^\"'\s<>]+\.zip", _get(SCDNR_DIGITAL_DATA, raw=True))))
    log(f"SCGS index: {len(scgs_index)} quadrangles; GIS table: {len(scgs_gis)}; FTP files: {len(ftp)}")
    records = build_catalog(rows, themes, pages, scgs_index, scgs_gis, ftp, retrieved_at)
    summary = summarize(records) | {"retrieved_at": retrieved_at}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sc_catalog.json").write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    log(json.dumps(summary, indent=1))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "catalog")
    parser.add_argument("--checkpoints", type=Path, default=ROOT / ".checkpoints" / "catalog")
    args = parser.parse_args()
    run(args.out, args.checkpoints)


if __name__ == "__main__":
    main()
