"""Which South Carolina 1:24,000 quadrangle maps have a published GIS dataset, and which only a PDF.

Reads the source catalog already on disk (data/catalog/sc_catalog.json, built by harvest.catalog from the
NGMDB product pages, the SCGS 1:24,000 index and GIS table, and the SCDNR FTP folder) and the extra GIS
sources merge.build knows about (merge.build.EXTRA_SOURCES). It makes no network requests: the product
pages were read when the catalog was built, so a rebuild is offline and gives the same file.

Writes data/catalog/quad_gis.json: for every 1:24,000 map (SCGS FTP packages without a catalog scale
count, scale flagged inferred), its id, quadrangles, year, format, download URLs, record URL and terms:

  gems                     GeMS package (NGMDB download)
  shapefile                polygon shapefiles (SCDNR FTP package)
  gis_download             another GIS download linked from the product page
  gis_not_readable         GIS published in a form merge.build cannot read here (reason in `note`)
  gis_listed_no_download   a catalog says GIS exists, but no public download is linked
  pdf_only                 online (PDF or NGMDB product page), no GIS
  not_online               no online copy listed

Terms are given only where a rule states them (U.S. Geological Survey publications are U.S. Government
works), flagged inferred because the record itself does not say; otherwise null. See docs/quad_gis.md.

    python -m harvest.quad_gis [--out data/catalog/quad_gis.json]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog" / "sc_catalog.json"
OUT = ROOT / "data" / "catalog" / "quad_gis.json"
QUAD_SCALE = 24000

GIS_DOWNLOAD = ("gems", "shapefile", "gis_download")
NO_PUBLIC_GIS = ("gis_listed_no_download", "gis_not_readable")
TERMS_BY_PUBLISHER = {
    "U.S. Geological Survey": "Public domain (U.S. Government work)",
}


def _is_quad(rec: dict) -> bool:
    if rec.get("scale") == QUAD_SCALE:
        return True
    # Every SCGS FTP quadrangle package is 1:24,000 (merge.build.SCGS_SCALE); drafts have no catalog scale.
    return not rec.get("scale") and bool((rec.get("availability") or {}).get("scgs_ftp"))


def _polys(urls) -> list[str]:
    return [u for u in urls or [] if re.search(r"_poly\.zip$", u, re.I)]


def _classify(rec: dict, extra: dict | None) -> tuple[str, list[str], str | None]:
    a = rec.get("availability") or {}
    if a.get("gems_download"):
        return "gems", [a["gems_download"]], None
    if _polys(a.get("scgs_ftp")):
        return "shapefile", _polys(a.get("scgs_ftp")), None
    if a.get("gis_download"):
        return "gis_download", [a["gis_download"]], None
    if extra:
        if extra.get("skip"):
            return "gis_not_readable", [u for u in [extra.get("download")] if u], extra["skip"]
        if extra.get("kind") == "shapefile":
            return "shapefile", list(extra.get("downloads") or []), extra.get("note")
        if extra.get("download"):
            return "gems", [extra["download"]], extra.get("note")
    if a.get("gis"):
        return "gis_listed_no_download", [], None
    if a.get("online") or a.get("pdf"):
        return "pdf_only", list(a.get("pdf") or []), None
    return "not_online", [], None


def _terms(rec: dict) -> dict | None:
    value = TERMS_BY_PUBLISHER.get(rec.get("publisher") or "")
    return {"value": value, "inferred": True, "basis": f"{rec['publisher']} publication"} if value else None


def build(catalog: list[dict], extra_sources: list[dict] | None = None) -> dict:
    if extra_sources is None:
        from merge.build import EXTRA_SOURCES as extra_sources
    extra = {e["id"]: e for e in extra_sources}
    records = []
    for rec in catalog:
        if not _is_quad(rec):
            continue
        fmt, urls, note = _classify(rec, extra.get(rec["id"]))
        out = {
            "id": rec["id"],
            "title": rec.get("title"),
            "quads": list(rec.get("quadrangles") or []),
            "year": rec.get("year"),
            "scale": rec.get("scale") or QUAD_SCALE,
            "scale_inferred": not rec.get("scale"),
            "publisher": rec.get("publisher"),
            "status": rec.get("status"),
            "format": fmt,
            "download": urls,
            "record_url": rec.get("ngmdb_url"),
            "terms": _terms(rec),
        }
        if note:
            out["note"] = note
        records.append(out)
    summary = {"total": len(records),
               "with_gis_download": sum(r["format"] in GIS_DOWNLOAD for r in records),
               "gis_without_public_download": sum(r["format"] in NO_PUBLIC_GIS for r in records),
               "pdf_only": sum(r["format"] == "pdf_only" for r in records),
               "not_online": sum(r["format"] == "not_online" for r in records)}
    return {
        "about": "South Carolina 1:24,000 quadrangle maps by what is published: GIS dataset or PDF only "
                 "(harvest/quad_gis.py, from data/catalog/sc_catalog.json; no network requests).",
        "provenance": {"source_id": "sc-catalog", "locator": "records[].id = id in data/catalog/sc_catalog.json",
                       "extraction_method": "catalog_import", "confidence": 1.0},
        "requests_made": 0,
        "summary": summary,
        "records": records,
    }


def write(data: dict, path: Path = OUT) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    data = build(json.loads(CATALOG.read_text()))
    path = write(data, args.out)
    print(f"wrote {path}: {json.dumps(data['summary'])}")


if __name__ == "__main__":
    main()
