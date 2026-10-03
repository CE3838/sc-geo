"""Compact reference list for the viewer's property card.

Writes web/data/geology/references.json from the source catalog
(data/catalog/sc_catalog.json): for every record with a footprint, its
id, citation, year, scale, bounding box and an https link. The viewer
picks the records whose box covers a clicked point and ranks them by map
scale (most detailed first), then by year (newest first); `covering` here
is the same ranking, used by the tests.

Each record's `id` is its id in the catalog, which holds the full record
and its provenance.

    python -m merge.references [--out web/data/geology/references.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog" / "sc_catalog.json"
OUT = ROOT / "web" / "data" / "geology" / "references.json"


def _https(url) -> str | None:
    return url if isinstance(url, str) and url.startswith("https://") else None


def _url(rec: dict) -> str | None:
    avail = rec.get("availability") or {}
    for url in (rec.get("ngmdb_url"), avail.get("doi"), *(avail.get("pdf") or [])):
        if _https(url):
            return url
    return None


def record(rec: dict) -> dict | None:
    bbox = rec.get("bbox")
    if not bbox or len(bbox) != 4:
        return None
    out = {
        "id": rec["id"],
        "citation": rec.get("citation") or rec.get("title"),
        "year": rec.get("year"),
        "scale": rec.get("scale"),
        "bbox": [round(float(v), 4) for v in bbox],
        "url": _url(rec),
    }
    if rec.get("status") == "draft":
        out["draft"] = True
    return {k: v for k, v in out.items() if v is not None}


def build(catalog: list[dict]) -> dict:
    records = [r for r in (record(rec) for rec in catalog) if r]
    return {
        "provenance": {
            "source_id": "sc-catalog",
            "locator": "records[].id = id in data/catalog/sc_catalog.json",
            "extraction_method": "catalog_import",
            "confidence": 1.0,
        },
        "records": records,
    }


def write(catalog: list[dict], path: Path = OUT) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build(catalog), separators=(",", ":")))
    return path


# A footprint wider or taller than South Carolina (about 4.8 by 3.2 degrees)
# is a regional work; its scale says nothing about detail at a point, so it
# ranks as if its scale were unknown. Same rule as web/card.js keyReferences.
MAX_SPAN = (5.0, 3.5)


def rank_key(r: dict) -> tuple:
    w, s, e, n = r["bbox"]
    local = e - w <= MAX_SPAN[0] and n - s <= MAX_SPAN[1]
    return ((r.get("scale") if local else None) or 10**12, -(r.get("year") or 0))


def covering(records: list[dict], lng: float, lat: float) -> list[dict]:
    hits = [r for r in records if r["bbox"][0] <= lng <= r["bbox"][2] and r["bbox"][1] <= lat <= r["bbox"][3]]
    return sorted(hits, key=rank_key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    path = write(json.loads(CATALOG.read_text()), args.out)
    print(f"wrote {path} ({path.stat().st_size // 1000} kB)")


if __name__ == "__main__":
    main()
