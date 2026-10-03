"""Harvest South Carolina units from the USGS State Geologic Map Compilation.

Downloads the SGMC polygons for one state from an ArcGIS FeatureServer, page
by page, and writes GeoJSON plus a metadata file for the web viewer.

The job is resumable: each page is saved under the checkpoint directory and
skipped on the next run, so a failed run picks up where it stopped. The
checkpoints are removed after a successful run. One state
is a few hundred features, far inside the 6-hour job limit.

    python -m harvest.sgmc [--out web/data/geology] [--checkpoints .checkpoints/sgmc]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from model.provenance import ExtractionMethod, StoredValue

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ID = "usgs-sgmc"

Fetch = Callable[[str, dict[str, str], dict[str, str]], Any]

# Period (or era) names as they appear in SGMC age strings, mapped to the
# class used to color the map. Checked from most to least specific.
_AGE_TERMS = [
    ("Quaternary", "Quaternary"),
    ("Tertiary-Neogene", "Neogene"),
    ("Tertiary-Paleogene", "Paleogene"),
    ("Tertiary", "Tertiary"),
    ("Cretaceous", "Cretaceous"),
    ("Jurassic", "Jurassic"),
    ("Triassic", "Triassic"),
    ("Permian", "Permian"),
    ("Carboniferous", "Carboniferous"),
    ("Devonian", "Devonian"),
    ("Silurian", "Silurian"),
    ("Ordovician", "Ordovician"),
    ("Cambrian", "Cambrian"),
    ("Neoproterozoic", "Neoproterozoic"),
    ("Mesoproterozoic", "Mesoproterozoic"),
    ("Paleoproterozoic", "Paleoproterozoic"),
    ("Archean", "Archean"),
    ("Cenozoic", "Cenozoic"),
    ("Mesozoic", "Mesozoic"),
    ("Paleozoic", "Paleozoic"),
    ("Proterozoic", "Proterozoic"),
    ("preCambrian", "Precambrian"),
]


def age_class(age: str | None) -> str:
    """Period-level class for an SGMC age string such as
    'Phanerozoic - Cenozoic - Quaternary - Pleistocene'."""
    if not age:
        return "Unknown"
    parts = [p.strip() for p in age.split(" - ")]
    for term, cls in _AGE_TERMS:
        if term in parts:
            return cls
    return "Unknown"


def lith_class(generalized: str | None) -> str:
    """First part of SGMC's generalized lithology, e.g. 'Igneous, intrusive' -> 'Igneous'."""
    if not generalized:
        return "Unknown"
    return generalized.split(",")[0].strip() or "Unknown"


def _contact_headers() -> dict[str, str]:
    agent = "sc-geo-harvest/0.1 (+https://github.com/CE3838/sc-geo"
    email = os.environ.get("CONTACT_EMAIL", "").strip()
    return {"User-Agent": f"{agent}; {email})" if email else f"{agent})"}


def http_fetch(url: str, params: dict[str, str], headers: dict[str, str], tries: int = 4) -> Any:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(tries):
        try:
            req = urllib.request.Request(full, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            if isinstance(data, dict) and "error" in data:
                raise OSError(f"service error: {data['error']}")
            return data
        except (OSError, ValueError):
            if attempt == tries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


class _Fields:
    """Case-insensitive access to service field names (hosted copies differ)."""

    def __init__(self, layer: dict):
        self.names = {f["name"].upper(): f["name"] for f in layer.get("fields", [])}

    def name(self, *candidates: str) -> str | None:
        for c in candidates:
            if c.upper() in self.names:
                return self.names[c.upper()]
        return None


def _get(props: dict, *keys: str):
    upper = {k.upper(): v for k, v in props.items()}
    for k in keys:
        v = upper.get(k.upper())
        if v not in (None, ""):
            return v
    return None


def _join(props: dict, *keys: str) -> str | None:
    vals = [str(v) for k in keys if (v := _get(props, k)) is not None]
    return ", ".join(vals) or None


def _normalize(feature: dict, oid_field: str) -> dict:
    p = feature["properties"]
    oid = _get(p, oid_field)
    unit_link = _get(p, "UNIT_LINK")
    lith = _get(p, "GENERALIZED_LITH", "GENERALIZE")
    is_water = (lith or "").strip().lower() == "water"
    record = {
        "unit": _get(p, "SGMC_LABEL"),
        "orig_label": _get(p, "ORIG_LABEL"),
        "name": _get(p, "UNIT_NAME"),
        "age_min": _get(p, "AGE_MIN"),
        "age_max": _get(p, "AGE_MAX"),
        "major": _join(p, "MAJOR1", "MAJOR2", "MAJOR3"),
        "minor": _join(p, "MINOR1", "MINOR2", "MINOR3", "MINOR4", "MINOR5"),
        "lith": lith,
        "ref_id": _get(p, "REF_ID"),
        "ngmdb": _get(p, "NGMDB1"),
    }
    # Attributes read directly from SGMC.
    read = StoredValue(
        value=record,
        source_id=f"{SOURCE_ID}:{record['ref_id'] or 'unknown'}",
        page=None,
        locator=f"{oid_field}={oid}; UNIT_LINK={unit_link}",
        extraction_method=ExtractionMethod.GIS_IMPORT,
        confidence=1.0,
    )
    # Classes derived here for map colors: an inference, flagged as such.
    derived = StoredValue(
        value={
            "age_class": "Water" if is_water else age_class(record["age_max"]),
            "lith_class": "Water" if is_water else lith_class(lith),
        },
        source_id=read.source_id,
        page=None,
        locator=read.locator,
        extraction_method=ExtractionMethod.INFERENCE,
        confidence=0.9,
        inferred=True,
    )
    props = {k: v for k, v in record.items() if v is not None}
    props.update(derived.value)
    props.update(
        source_id=read.source_id,
        locator=read.locator,
        extraction_method=read.extraction_method.value,
        confidence=read.confidence,
        classes_inferred=derived.inferred,
    )
    return {"type": "Feature", "geometry": feature["geometry"], "properties": props}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(path)


def _harvest_from(url, state, ckpt_root, fetch, headers, log):
    layer = fetch(url, {"f": "json"}, headers)
    fields = _Fields(layer)
    state_field = fields.name("STATE")
    if not state_field:
        raise RuntimeError(f"{url} has no STATE field")
    oid_field = layer.get("objectIdField") or fields.name("OBJECTID") or "OBJECTID"
    where = f"{state_field}='{state}'"
    count = int(fetch(f"{url}/query", {"where": where, "returnCountOnly": "true", "f": "json"}, headers)["count"])
    page_size = max(1, min(int(layer.get("maxRecordCount") or 1000), 1000))
    ckpt = ckpt_root / hashlib.sha1(f"{url}|{where}|{count}".encode()).hexdigest()[:16]
    log(f"{count} features for {state} from {url}; {page_size} per page; checkpoints in {ckpt}")

    features: list[dict] = []
    for offset in range(0, count, page_size):
        page_file = ckpt / f"page-{offset:06d}.json"
        if page_file.exists():
            page = json.loads(page_file.read_text())
        else:
            page = fetch(f"{url}/query", {
                "where": where,
                "outFields": "*",
                "orderByFields": oid_field,
                "resultOffset": str(offset),
                "resultRecordCount": str(page_size),
                "outSR": "4326",
                "geometryPrecision": "5",
                # About 20 m; the source maps are 1:500,000.
                "maxAllowableOffset": "0.0002",
                "f": "geojson",
            }, headers)
            _write_json(page_file, page)
            log(f"  fetched features {offset}-{offset + len(page['features']) - 1}")
        features.extend(page["features"])
    if len(features) != count:
        raise RuntimeError(f"got {len(features)} features, expected {count}")
    return features, oid_field, count, ckpt


def run(urls: list[str], state: str, out_dir: Path, checkpoint_dir: Path,
        fetch: Fetch = http_fetch, log: Callable[..., None] = print) -> dict:
    headers = _contact_headers()
    last_error: Exception | None = None
    for url in urls:
        try:
            raw, oid_field, count, ckpt = _harvest_from(url, state, Path(checkpoint_dir), fetch, headers, log)
            break
        except (OSError, RuntimeError, KeyError, ValueError) as err:
            # Never echo headers here; they carry the contact email.
            log(f"{url} failed: {type(err).__name__}: {err}")
            last_error = err
    else:
        raise last_error or RuntimeError("no feature service URLs given")

    features = [_normalize(f, oid_field) for f in raw if f.get("geometry")]
    references: dict[str, str] = {}
    for f in raw:
        ref_id = _get(f["properties"], "REF_ID")
        ref = _get(f["properties"], "REFERENCE")
        if ref_id and ref:
            references.setdefault(ref_id, ref)

    out = Path(out_dir)
    name = f"sgmc-{state.lower()}"
    _write_json(out / f"{name}.geojson", {"type": "FeatureCollection", "features": features})
    meta = {
        "source_id": SOURCE_ID,
        "state": state,
        "source_url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": count,
        "references": dict(sorted(references.items())),
        "classes": {
            "age_class": "Period of the unit's oldest age (AGE_MAX); inferred",
            "lith_class": "First part of SGMC generalized lithology; inferred",
        },
    }
    _write_json(out / f"{name}.meta.json", meta)
    # Checkpoints only exist to resume a failed run; the next run starts fresh.
    shutil.rmtree(ckpt, ignore_errors=True)
    log(f"wrote {len(features)} features to {out / (name + '.geojson')}")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default="SC")
    parser.add_argument("--out", type=Path, default=ROOT / "web" / "data" / "geology")
    parser.add_argument("--checkpoints", type=Path, default=ROOT / ".checkpoints" / "sgmc")
    args = parser.parse_args()
    sources = json.loads((ROOT / "config" / "sources.json").read_text())
    run(sources[SOURCE_ID]["feature_services"], args.state, args.out, args.checkpoints)


if __name__ == "__main__":
    main()
