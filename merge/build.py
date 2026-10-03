"""Build the merged geologic map of South Carolina.

1. Pick GIS sources: every catalog record with a GeMS download, the USGS
   Charleston-region surficial database, and SGMC (from harvest/sgmc.py).
2. Download each once into .cache/sources (resumable; never committed).
3. Normalize each to the merge schema (merge/sources.py), cached in
   .cache/normalized.
4. Overlay into one seamless layer per kind (surficial, bedrock) with
   confidence and alternatives (merge/overlay.py, needs shapely).

Writes web/data/geology/merged-{surficial,bedrock}.geojson and
merged-sources.json (every source considered, used or skipped, and why).

    python -m merge.build [--normalize-only]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from harvest.sgmc import _contact_headers
from merge import classes, sources
from model import gisio
from model.units import Lexicon

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
OUT = ROOT / "web" / "data" / "geology"
NORMALIZE_VERSION = 4

EXTRA_SOURCES = [
    {
        "id": "ngmdb:100396",
        "download": "https://www.sciencebase.gov/catalog/file/get/620d314ed34e6c7e83ba9a2d?f=__disk__dc%2F51%2Fec%2Fdc51ecc70aa588113f6906d77a7c950b47b0282c",
        "note": "USGS data release https://doi.org/10.5066/P9HB0RFE (open-access shapefiles)",
    },
]


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def download(url: str, dest: Path, log: Callable[..., None] = print, tries: int = 4) -> Path:
    if dest.exists() and zipfile.is_zipfile(dest):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=_contact_headers())
            with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            if not zipfile.is_zipfile(tmp):
                raise OSError("download is not a zip file")
            tmp.replace(dest)
            log(f"  downloaded {dest.name} ({dest.stat().st_size // 1_000_000} MB)")
            return dest
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def source_list(catalog: list[dict]) -> list[dict]:
    by_id = {r["id"]: r for r in catalog}
    out = []
    for r in catalog:
        if r["availability"].get("gems_download"):
            out.append({**r, "download": r["availability"]["gems_download"]})
    for extra in EXTRA_SOURCES:
        rec = by_id.get(extra["id"], {"id": extra["id"]})
        if not any(s["id"] == extra["id"] for s in out):
            out.append({**rec, **extra})
    return out


def _meta(rec: dict) -> dict:
    return {"id": rec["id"], "title": rec.get("title"), "scale": rec.get("scale"), "year": rec.get("year"),
            "citation": rec.get("citation") or rec.get("title")}


def normalize_zip(zf: zipfile.ZipFile, rec: dict) -> list[dict]:
    base = gisio.zip_layer(zf, "MapUnitPolys")
    if base is None:
        raise ValueError("no MapUnitPolys layer")
    units = sources.gems_units(gisio.zip_csv(zf, "DescriptionOfMapUnits"))
    # The NGMDB shapefile export drops some fields (IdentityConfidence); the
    # MapUnitPolys CSV beside it has them, keyed by OBJECTID.
    extra = {str(r.get("OBJECTID")): r for r in gisio.zip_csv(zf, "MapUnitPolys") if r.get("OBJECTID")}
    meta = _meta(rec)
    out = []
    for f in gisio.read_layer_lonlat(zf, base):
        attrs = {**extra.get(str(f["properties"].get("OBJECTID")), {}), **f["properties"]}
        feat = sources.unit_feature(f["geometry"], attrs, units, meta)
        if feat is not None:
            out.append(feat)
    return out


def normalize_all(catalog: list[dict], cache: Path = CACHE, log: Callable[..., None] = print,
                  fetch: Callable[[str, Path], Path] | None = None) -> tuple[list[dict], list[dict]]:
    fetch = fetch or (lambda url, dest: download(url, dest, log))
    features, report = [], []
    for rec in source_list(catalog):
        sid = rec["id"]
        norm = cache / "normalized" / f"{_safe(sid)}.v{NORMALIZE_VERSION}.geojson"
        try:
            if norm.exists():
                feats = json.loads(norm.read_text())["features"]
            else:
                path = fetch(rec["download"], cache / "sources" / f"{_safe(sid)}.zip")
                with zipfile.ZipFile(path) as zf:
                    feats = normalize_zip(zf, rec)
                norm.parent.mkdir(parents=True, exist_ok=True)
                norm.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
            layers = {}
            for f in feats:
                layers[f["properties"]["layer"]] = layers.get(f["properties"]["layer"], 0) + 1
            report.append({**_meta(rec), "status": "used", "polygons": len(feats), "layers": layers,
                           "download": rec["download"]})
            features += feats
            log(f"{sid}: {len(feats)} polygons {layers}")
        except (OSError, ValueError, zipfile.BadZipFile, KeyError) as err:
            report.append({**_meta(rec), "status": "skipped", "reason": f"{type(err).__name__}: {err}",
                           "download": rec.get("download")})
            log(f"{sid}: skipped ({err})")
    return features, report


def sgmc_features(path: Path = OUT / "sgmc-sc.geojson") -> list[dict]:
    if not path.exists():
        return []
    return [sources.sgmc_feature(f["geometry"], f["properties"]) for f in json.loads(path.read_text())["features"]]


def run(normalize_only: bool = False, log: Callable[..., None] = print) -> dict:
    catalog = json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text())
    lex = Lexicon(json.loads((ROOT / "data" / "lexicon" / "geolex_sc.json").read_text()))
    features, report = normalize_all(catalog, log=log)
    sgmc = sgmc_features()
    if sgmc:
        report.append({"id": "usgs-sgmc", **sources.SGMC_SOURCE, "status": "used", "polygons": len(sgmc)})
    else:
        report.append({"id": "usgs-sgmc", "status": "skipped", "reason": "run python -m harvest.sgmc first"})
    features += sgmc
    summary = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "sources": report, "input_polygons": len(features)}
    if not normalize_only:
        from merge import overlay  # needs shapely

        OUT.mkdir(parents=True, exist_ok=True)
        all_units, all_sources = {}, {}
        for layer in ("surficial", "bedrock"):
            merged = overlay.merge(features, lex, layer)
            polys, units, srcs = split_tables(merged)
            all_units.update(units)
            all_sources.update(srcs)
            (OUT / f"merged-{layer}.geojson").write_text(
                json.dumps({"type": "FeatureCollection", "features": polys}, separators=(",", ":")))
            summary[layer] = {"polygons": len(polys),
                              "by_source": dict(sorted(_count(polys, "source").items(), key=lambda kv: -kv[1]))}
            log(f"{layer}: {len(polys)} merged polygons")
        (OUT / "merged-units.json").write_text(json.dumps(all_units, separators=(",", ":")))
        (OUT / "merged-legend.json").write_text(json.dumps(
            {"age": classes.AGE_CLASSES, "material": classes.MATERIAL_CLASSES}, indent=1))
        summary["source_details"] = all_sources
        (OUT / "merged-sources.json").write_text(json.dumps(summary, indent=1))
    return summary


POLY_FIELDS = ("source", "map_unit", "layer", "identity_confidence", "locator", "extraction_method", "confidence",
               "conf", "conf_base", "agreement", "n_sources", "research_support", "alternatives", "derived_inferred")
UNIT_FIELDS = ("source", "map_unit", "name", "full_name", "formation", "unit_name", "canonical", "age", "age_ma",
               "geomaterial", "lith", "description")
SOURCE_FIELDS = ("title", "citation", "scale", "year")


def _round(c, nd=6):
    return round(c, nd) if isinstance(c, float) else [_round(x, nd) for x in c]


def split_tables(features: list[dict]) -> tuple[list[dict], dict, dict]:
    """GeMS-like output: lean polygons, a unit table and a source table."""
    polys, units, srcs = [], {}, {}
    for f in features:
        p = f["properties"]
        key = f"{p['source']}|{p['map_unit']}"
        lean = {k: p.get(k) for k in POLY_FIELDS}
        lean.update(unit=key, age_class=classes.age_class(p.get("age_ma")), material_class=classes.material_class(p))
        polys.append({"type": "Feature", "properties": lean,
                      "geometry": {"type": f["geometry"]["type"], "coordinates": _round(f["geometry"]["coordinates"])}})
        units.setdefault(key, {k: p.get(k) for k in UNIT_FIELDS})
        srcs.setdefault(p["source"], {"title": p.get("source_title"), **{k: p.get(k) for k in SOURCE_FIELDS[1:]}})
    return polys, units, srcs


def _count(feats, key):
    out = {}
    for f in feats:
        k = f["properties"].get(key)
        out[k] = out.get(k, 0) + 1
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--normalize-only", action="store_true")
    args = parser.parse_args()
    summary = run(args.normalize_only)
    print(json.dumps({k: v for k, v in summary.items() if k != "sources"}, indent=1))


if __name__ == "__main__":
    main()
