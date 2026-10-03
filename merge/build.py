"""Build the merged geologic map of South Carolina.

1. Pick GIS sources (source_list): every catalog record with a GeMS
   download; else its SCGS FTP polygon shapefiles (merge/scgs.py); else its
   GIS download; plus EXTRA_SOURCES (USGS Charleston-region and Greenville
   1x2 degree GeMS databases, SCGS quadrangles the catalog did not link) and
   SGMC (from harvest/sgmc.py). Maps that cannot be read here (file
   geodatabase only, no public GIS, or coarser than 1:1,000,000) are listed
   as skipped with the reason, without downloading them.
2. Download each once into .cache/sources (resumable; never committed).
3. Normalize each to the merge schema (merge/sources.py), cached in
   .cache/normalized.
4. Overlay into one seamless layer per kind (surficial, bedrock) with
   confidence and alternatives (merge/overlay.py, needs shapely).

Writes web/data/geology/merged-{surficial,bedrock}.geojson and
merged-sources.json (every source considered, used or skipped, and why),
plus references.json (merge/references.py: catalog records with their
footprints, for the viewer's property card; written even with
--normalize-only since it needs neither downloads nor shapely).

    python -m merge.build [--normalize-only]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from harvest.sgmc import _contact_headers
from merge import classes, references, scgs, sources
from model import gisio
from model.units import Lexicon

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
OUT = ROOT / "web" / "data" / "geology"
NORMALIZE_VERSION = 4

SCGS_FTP = "ftp://ftpdata.dnr.sc.gov/gisdata/glc/"
# Every SCGS FTP quadrangle package is 1:24,000 (SCGS digital-data table); drafts have no catalog scale.
SCGS_SCALE = 24000
# Coarser maps add nothing: SGMC (1:500,000) covers all of South Carolina, so they would never
# win anywhere and would only dilute agreement.
MAX_SCALE = 1_000_000

EXTRA_SOURCES = [
    {
        "id": "ngmdb:100396",
        "download": "https://www.sciencebase.gov/catalog/file/get/620d314ed34e6c7e83ba9a2d?f=__disk__dc%2F51%2Fec%2Fdc51ecc70aa588113f6906d77a7c950b47b0282c",
        "note": "USGS data release https://doi.org/10.5066/P9HB0RFE (open-access shapefiles)",
    },
    {
        "id": "ngmdb:13044",  # USGS I-2175, Greenville 1x2 degree quadrangle
        "download": "https://www.sciencebase.gov/catalog/file/get/63fe0860d34e70052b9b6ec7?f=__disk__ac%2Fee%2F3e%2Facee3ef6099b3cdc522c6e1c66add848d329ec87",
        "note": "USGS GeMS database https://www.sciencebase.gov/catalog/item/63fe0860d34e70052b9b6ec7 "
                "(Greenville-MIS-2175-OpenAccess.zip: shapefiles and CSV tables)",
    },
    # SCGS quadrangles on the FTP site that the catalog did not link (file codes 'dale0', 'savan').
    {"id": "ngmdb:77460", "kind": "shapefile", "downloads": [SCGS_FTP + "dale06glc_poly.zip"],
     "note": "SCDNR FTP package (ACE Basin project, 2006)"},
    {"id": "ngmdb:77446", "kind": "shapefile", "downloads": [SCGS_FTP + "savan07glc_poly.zip"],
     "note": "SCDNR FTP package (Bluffton area project, 2007)"},
    # GIS exists but cannot be read here, or is not public.
    {"id": "ngmdb:108478", "download": "https://pubs.usgs.gov/sim/3424/metadata/sim3424.gdb.zip",
     "skip": "file geodatabase only (sim3424.gdb.zip, no shapefile or GeMS open-access export); "
             "reading it needs GDAL"},
    {"id": "ngmdb:115932",
     "skip": "no public GIS download: SCGS Map Compilation 01 (1:100,000), GIS available from SCGS on request"},
    {"id": "ngmdb:115933",
     "skip": "no public GIS download: SCGS Map Compilation 02 (1:100,000), GIS available from SCGS on request"},
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
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            if not zipfile.is_zipfile(tmp):
                raise OSError("download is not a zip file")
            tmp.replace(dest)
            log(f"  downloaded {dest.name} ({dest.stat().st_size // 1_000_000} MB)")
            return dest
        except OSError as err:
            # A host that will not connect twice in a row is down: do not wait out every try.
            if attempt == tries - 1 or (attempt >= 1 and _host_down(err)):
                raise
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def _shapefile_source(rec: dict, urls: list[str]) -> dict:
    src = {**rec, "kind": "shapefile", "downloads": urls, "download": urls[0] if len(urls) == 1 else urls}
    if not src.get("scale") and any(u.startswith(SCGS_FTP) for u in urls):
        src.update(scale=SCGS_SCALE, scale_inferred=True)
    return src


def source_list(catalog: list[dict]) -> list[dict]:
    """GIS maps to merge: GeMS packages, SCGS FTP shapefiles, other GIS downloads, and EXTRA_SOURCES.

    Sources that cannot be used carry `skip` (the reason) and are reported, not downloaded."""
    by_id = {r["id"]: r for r in catalog}
    out = []
    for r in catalog:
        avail = r.get("availability", {})
        polys = [u for u in avail.get("scgs_ftp") or [] if re.search(r"_poly\.zip$", u, re.I)]
        if avail.get("gems_download"):
            out.append({**r, "kind": "gems", "download": avail["gems_download"]})
        elif polys:
            out.append(_shapefile_source(r, polys))
        elif avail.get("gis_download"):
            out.append(_shapefile_source(r, [avail["gis_download"]]))
    for extra in EXTRA_SOURCES:
        rec = by_id.get(extra["id"], {"id": extra["id"]})
        if not any(s["id"] == extra["id"] for s in out):
            src = {**rec, "kind": "gems", **extra}
            if src["kind"] == "shapefile":
                src = _shapefile_source(src, extra["downloads"])
            out.append(src)
    for s in out:
        if not s.get("skip") and (s.get("scale") or 0) > MAX_SCALE:
            s["skip"] = (f"map scale 1:{s['scale']:,} is coarser than 1:{MAX_SCALE:,}; SGMC (1:500,000) covers all "
                         f"of South Carolina, so this map would never win and would only dilute agreement")
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


def _host_down(err: Exception) -> bool:
    """A connection failure (the host is unreachable), not an error about one file."""
    if isinstance(err, urllib.error.HTTPError):
        return False
    if isinstance(err, urllib.error.URLError):
        return isinstance(err.reason, OSError)
    return isinstance(err, (TimeoutError, ConnectionError))


def _skip_dead_hosts(fetch: Callable[[str, Path], Path]) -> Callable[[str, Path], Path]:
    """After a host fails to connect, fail its other downloads at once, to stay in the time budget
    (e.g. the SCDNR FTP host serves about 35 packages)."""
    dead: set[str] = set()

    def guarded(url: str, dest: Path) -> Path:
        host = urllib.parse.urlparse(url).hostname
        if host in dead:
            raise OSError(f"{host} unreachable earlier in this run")
        try:
            return fetch(url, dest)
        except OSError as err:
            if _host_down(err):
                dead.add(host)
            raise

    return guarded


def normalize_shapefiles(rec: dict, cache: Path, fetch: Callable[[str, Path], Path],
                         lex: Lexicon | None = None) -> tuple[list[dict], dict]:
    """A plain-shapefile source (SCGS FTP packages): every polygon zip, then an extent check."""
    feats, files = [], []
    for url in rec["downloads"]:
        name = _safe(url.rsplit("/", 1)[-1].split("?")[0])
        path = fetch(url, cache / "sources" / f"{_safe(rec['id'])}__{name}")
        with zipfile.ZipFile(path) as zf:
            part, info = scgs.normalize_zip(zf, rec, lex)
        feats += part
        files.append({"url": url, **info})
    if not feats:
        raise ValueError("no map unit polygons")
    ext = scgs.extent(feats)
    if scgs.extent_check(ext, rec.get("bbox")) == "outside catalog bbox":
        raise ValueError(f"extent {ext} is outside catalog bbox {rec.get('bbox')}: wrong projection?")
    meta = {"format": "shapefile", "files": files}
    if rec.get("scale_inferred"):
        meta["notes"] = [f"scale 1:{rec['scale']:,} from the SCGS digital-data table (not in the catalog)"]
    return feats, meta


def normalize_all(catalog: list[dict], cache: Path = CACHE, log: Callable[..., None] = print,
                  fetch: Callable[[str, Path], Path] | None = None,
                  lex: Lexicon | None = None) -> tuple[list[dict], list[dict]]:
    fetch = _skip_dead_hosts(fetch or (lambda url, dest: download(url, dest, log)))
    features, report = [], []
    for rec in source_list(catalog):
        sid = rec["id"]
        if rec.get("skip"):
            report.append({**_meta(rec), "status": "skipped", "reason": rec["skip"], "download": rec.get("download")})
            log(f"{sid}: skipped ({rec['skip']})")
            continue
        norm = cache / "normalized" / f"{_safe(sid)}.v{NORMALIZE_VERSION}.geojson"
        try:
            if norm.exists():
                data = json.loads(norm.read_text())
                feats, meta = data["features"], data.get("meta", {})
            else:
                if rec.get("kind") == "shapefile":
                    feats, meta = normalize_shapefiles(rec, cache, fetch, lex)
                else:
                    path = fetch(rec["download"], cache / "sources" / f"{_safe(sid)}.zip")
                    with zipfile.ZipFile(path) as zf:
                        feats = normalize_zip(zf, rec)
                    meta = {"format": "GeMS shapefiles and CSV tables"}
                norm.parent.mkdir(parents=True, exist_ok=True)
                norm.write_text(json.dumps({"type": "FeatureCollection", "features": feats, "meta": meta}))
            layers = {}
            for f in feats:
                layers[f["properties"]["layer"]] = layers.get(f["properties"]["layer"], 0) + 1
            ext = scgs.extent(feats)
            report.append({**_meta(rec), "status": "used", "polygons": len(feats), "layers": layers,
                           "download": rec["download"], **meta, "extent": ext,
                           "extent_check": scgs.extent_check(ext, rec.get("bbox"))})
            features += feats
            log(f"{sid}: {len(feats)} polygons {layers}")
        except (OSError, ValueError, zipfile.BadZipFile, KeyError, IndexError, struct.error) as err:
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
    features, report = normalize_all(catalog, log=log, lex=lex)
    sgmc = sgmc_features()
    if sgmc:
        report.append({"id": "usgs-sgmc", **sources.SGMC_SOURCE, "status": "used", "polygons": len(sgmc)})
    else:
        report.append({"id": "usgs-sgmc", "status": "skipped", "reason": "run python -m harvest.sgmc first"})
    features += sgmc
    refs = references.write(catalog, OUT / "references.json")
    log(f"{refs.name}: {refs.stat().st_size // 1000} kB")
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
               "geomaterial", "lith", "description", "inferred_fields", "name_source")
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
