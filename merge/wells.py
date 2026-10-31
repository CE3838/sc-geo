"""Known wells, borings, cores, test holes and springs of the documents, for the viewer's Hydro folder.

Reads data/extracted (public catalog records only) and writes three files into web/data/sites/
(merge.package ships them as data/sites/):

* wells.geojson: one point per site (a well, boring, core, auger or test hole, test pit, CPT or spring of one
  document, or any site with water or rock tests), with its label, kind, citation (source, page, quote,
  locator), total depth, land-surface elevation (and its NAVD 88 conversion when stored), how many water and
  rock tests it has, and how far the point may be from the place (`r`, metres);
* water-tests.json and rock-tests.json: the tests of those sites, keyed by site id, columns once and one
  array per test, each with its page and quote.

A site is placed only by an inferred `derived_coordinates` stored for its own printed location or for the
observation with the same label in that document (merge.site_tests.site_key). Nothing is placed from a place
name. A site with no such coordinate is left out of all three files, and so is one whose coordinate may be
more than MAX_LOCATION_RADIUS_M from the place, judged from the printed precision (model.coords.location_radius).
Exact coordinates that are not inferred would be kept as they are. The full list, placed or not, stays in
site-tests.json (merge.site_tests). The format is in extract/README.md ("Known wells and tests for the map").

Run: python -m merge.wells [--out-dir web/data/sites]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from merge import site_tests
from merge.site_tests import _test_entry, _v, _value, site_key, tests_of
from model import coords

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = site_tests.EXTRACTED
CATALOG = site_tests.CATALOG
OUT_DIR = ROOT / "web" / "data" / "sites"

# Rule set by the user, 2026-10-30: show only sites whose location is known to within one mile.
MAX_LOCATION_RADIUS_M = 1609
WELL_KINDS = ("well", "boring", "core", "auger_hole", "test_pit", "cpt", "spring")
NOTES = ("Public data only, read from published documents. Each point is placed by a coordinate converted from "
         "the location printed in the source (inferred, flagged ci=1), never from a place name, and shown only "
         f"when it is within {MAX_LOCATION_RADIUS_M} m (1 mile) of the place by the printed precision (r). "
         "Every value keeps its source, page and verbatim quote. Units are as printed, never guessed. Each source "
         "keeps its own terms; cite it when reusing its data. Provided as is, without warranty of any kind.")
KEYS = {
    "id": "site id: source id # label compared without case, spaces or dashes",
    "l": "label as printed", "k": "kind (well, boring, core, auger_hole, test_pit, cpt, spring, other)",
    "s": "source id (see sources)", "p": "page of the printed location", "q": "verbatim quote of the location",
    "lc": "locator of the location value", "loc": "location as printed",
    "ci": "1: coordinates inferred (converted from the printed location)", "cf": "confidence of the coordinates",
    "d": "horizontal datum (null: not printed)", "a": "assumptions made in the conversion",
    "r": "radius in metres within which the place should lie (printed precision and datum)",
    "td": "total depth: v as printed, ft, p page, q quote, c confidence, i inferred, m method, lc locator",
    "el": "land-surface elevation: as td, plus d vertical datum and n88 the NAVD 88 conversion",
    "wt": "number of water tests (water-tests.json)", "rt": "number of rock tests (rock-tests.json)",
    "n": "observations in the document with this label",
}
WATER_COLUMNS = ["parameter", "name", "category", "value", "qualifier", "number", "range", "units", "date",
                 "top_ft", "bottom_ft", "depth_reference", "sample_id", "source_table", "page", "quote",
                 "confidence", "inferred", "locator"]
ROCK_COLUMNS = ["test_type", "type", "parameter", "value", "qualifier", "number", "range", "units", "date",
                "top_ft", "bottom_ft", "depth_reference", "sample_id", "rock_type", "standard", "source_table",
                "page", "quote", "confidence", "inferred", "locator"]
COLUMN_NOTES = ("One array per test, in `columns` order. parameter/test_type, value, units, date and sample_id are "
                "as printed; name, category and type are inferred normalized names; number/range/qualifier are "
                "read from the printed value; top_ft/bottom_ft are depths in feet (below land surface, or "
                "signed elevations when depth_reference is 'elevation'); page, quote, confidence, inferred "
                "(1 when the value was inferred) and locator cite the value.")


def _sv(x: dict | None, ft_key: str | None = None) -> dict | None:
    if not x:
        return None
    out = {"v": x.get("value")}
    norm = x.get("normalized") if isinstance(x.get("normalized"), dict) else {}
    if ft_key:
        out["ft"] = norm.get(ft_key, norm.get("min_ft"))
    out |= {"p": x.get("page"), "q": x.get("quote"), "c": x.get("confidence"), "i": int(bool(x.get("inferred"))),
            "m": x.get("extraction_method"), "lc": x.get("locator")}
    return out


def _elevation(obs: dict | None) -> dict | None:
    el = _v(obs or {}, "elevation")
    if not el:
        return None
    out = _sv(el, "min_ft")
    datum = _v(obs, "datum")
    out["d"] = datum.get("normalized") if datum else None
    n = el.get("navd88")
    if n:
        val = n.get("value") or {}
        out["n88"] = {"ft": val.get("min_ft"), "c": n.get("confidence"), "i": int(bool(n.get("inferred", True))),
                      "m": n.get("extraction_method"), "cv": n.get("conversion"), "p": n.get("page")}
    return out


def _placement(records: list[dict], bbox) -> tuple[dict, dict, dict] | None:
    """(location value, derived coordinate, radius) of the best-placed record (smallest radius); None if none."""
    best = None
    for rec in records:
        loc = _v(rec, "location")
        d = loc and loc.get("derived_coordinates")
        if not d:
            continue
        if not d.get("inferred", True):
            rad = {"radius_m": None, "basis": ["exact coordinates"]}
        else:
            rad = coords.location_radius(loc.get("value"), assume_state_plane_nad83=bool(d.get("datum_assumed")),
                                         bbox=bbox) or {"radius_m": None, "basis": ["precision not readable"]}
        rank = rad["radius_m"] if rad["radius_m"] is not None else (0 if not d.get("inferred", True) else 1e12)
        if best is None or rank < best[0]:
            best = (rank, loc, d, rad)
    return best[1:] if best else None


def _row(entry: dict, columns: list[str]) -> list:
    val = entry["value"]
    f = entry["fields"].get("value") or {}
    depth = entry.get("depth") or {}
    cell = {
        "parameter": (entry.get("parameter") or {}).get("as_printed") if isinstance(entry.get("parameter"), dict)
        else entry.get("parameter"),
        "name": (entry.get("parameter") or {}).get("name") if isinstance(entry.get("parameter"), dict) else None,
        "category": (entry.get("parameter") or {}).get("category") if isinstance(entry.get("parameter"), dict)
        else None,
        "test_type": (entry.get("test_type") or {}).get("as_printed"),
        "type": (entry.get("test_type") or {}).get("type"),
        "value": val.get("as_printed"), "qualifier": val.get("qualifier"), "number": val.get("number"),
        "range": [val["min"], val["max"]] if "min" in val else None, "units": val.get("units"),
        "date": entry.get("date"), "top_ft": depth.get("top_ft"), "bottom_ft": depth.get("bottom_ft"),
        "depth_reference": depth.get("reference"),
        "page": f.get("page"), "quote": f.get("quote"), "confidence": f.get("confidence"),
        "inferred": int(bool(f.get("inferred"))), "locator": f.get("locator"),
    }
    for k in ("sample_id", "rock_type", "standard", "source_table"):
        cell[k] = entry.get(k)
    return [cell[c] for c in columns]


def _source(rec: dict, doc: dict) -> dict:
    out = {k: doc.get(k) or rec.get(k) for k in ("citation", "title", "year", "publisher")}
    out["url"] = rec.get("ngmdb_url") or (rec.get("availability") or {}).get("doi") or None
    return out


def _catalog(path: Path = CATALOG) -> dict[str, dict]:
    return {r["id"]: r for r in json.loads(Path(path).read_text())}


def build(extracted_dir: Path = EXTRACTED, catalog: dict | None = None) -> dict:
    catalog = catalog if catalog is not None else _catalog()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    features, water, rock, sources = [], {}, {}, {}
    kept, no_loc, too_far = Counter(), Counter(), Counter()
    for path in sorted(Path(extracted_dir).glob("*.json")):
        doc = json.loads(path.read_text())
        sid = doc.get("source_id")
        rec = catalog.get(sid)
        if rec is None:
            continue
        sites: dict[str, dict] = {}

        def site(key: str, loc_text) -> dict:
            where = key or (f"location:{site_key(loc_text)}" if loc_text else "unplaced")
            return sites.setdefault(where, {"id": f"{sid}#{where}", "key": key, "obs": [], "tests": [],
                                            "label": None, "kind": None})
        by_label: dict[str, list[dict]] = {}
        for o in doc.get("observations", []):
            key = site_key(_value(o, "label"))
            if key:
                by_label.setdefault(key, []).append(o)
            if o.get("kind") in WELL_KINDS and (key or _value(o, "location")):
                s = site(key, _value(o, "location"))
                if not key:
                    s["obs"].append(o)
        for section in site_tests.TESTS:
            for test in tests_of(doc, section):
                key = site_key(_value(test, "observation"))
                s = site(key, _value(test, "location"))
                s["tests"].append((section, test))
                s["label"] = s["label"] or _value(test, "observation")
                s["kind"] = s["kind"] or test.get("kind")
        for where, s in sites.items():
            obs = by_label.get(s["key"], []) if s["key"] else s["obs"]
            first = next((o for o in obs if o.get("kind") in WELL_KINDS), obs[0] if obs else None)
            kind = (first or {}).get("kind") if (first or {}).get("kind") in WELL_KINDS else (s["kind"] or
                                                                                              (first or {}).get("kind"))
            label = _value(first, "label") if first and _value(first, "label") else s["label"]
            place = _placement([t for _, t in s["tests"]] + obs, rec.get("bbox"))
            if place is None:
                no_loc[kind] += 1
                continue
            loc, d, rad = place
            inferred = bool(d.get("inferred", True))
            if inferred and (rad["radius_m"] is None or rad["radius_m"] > MAX_LOCATION_RADIUS_M):
                too_far[kind] += 1
                continue
            kept[kind] += 1
            with_depth = next((o for o in obs if _v(o, "total_depth")), None)
            with_el = next((o for o in obs if _v(o, "elevation")), None)
            obs_for_tests = next((o for o in obs if o.get("kind") in WELL_KINDS), first)
            w_rows = [_row(_test_entry(sec, t, obs_for_tests, sid), WATER_COLUMNS)
                      for sec, t in s["tests"] if sec == "water_tests"]
            r_rows = [_row(_test_entry(sec, t, obs_for_tests, sid), ROCK_COLUMNS)
                      for sec, t in s["tests"] if sec == "rock_tests"]
            props = {"id": s["id"], "l": label, "k": kind, "s": sid, "p": loc.get("page"), "q": loc.get("quote"),
                     "lc": loc.get("locator"), "loc": loc.get("value"), "ci": int(inferred),
                     "cf": d.get("confidence"), "d": d.get("datum"), "a": d.get("assumptions") or [],
                     "r": rad["radius_m"],
                     "td": _sv(_v(with_depth or {}, "total_depth"), "max_ft"), "el": _elevation(with_el),
                     "wt": len(w_rows), "rt": len(r_rows), "n": len(obs)}
            props = {k: v for k, v in props.items() if v is not None or k in ("r", "d")}
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [
                round(d["value"]["lon"], 6), round(d["value"]["lat"], 6)]}, "properties": props})
            if w_rows:
                water[s["id"]] = {"label": label, "source_id": sid, "rows": w_rows}
            if r_rows:
                rock[s["id"]] = {"label": label, "source_id": sid, "rows": r_rows}
            sources[sid] = _source(rec, doc)
    counts = {"features": len(features), "kept": dict(kept), "no_location": dict(no_loc),
              "radius_over_limit": dict(too_far)}
    head = {"version": 1, "generated": now, "notes": NOTES, "max_location_radius_m": MAX_LOCATION_RADIUS_M}

    def tests_doc(fmt, columns, sites_):
        return {"format": fmt, **head, "columns": columns, "column_notes": COLUMN_NOTES,
                "counts": {"sites": len(sites_), "tests": sum(len(x["rows"]) for x in sites_.values())},
                "sources": {k: sources[k] for k in sorted({x["source_id"] for x in sites_.values()})},
                "sites": sites_}
    return {
        "wells": {"type": "FeatureCollection", "format": "sc-geo known wells", **head, "keys": KEYS,
                  "counts": counts, "sources": sources, "features": features},
        "water": tests_doc("sc-geo water tests", WATER_COLUMNS, water),
        "rock": tests_doc("sc-geo rock tests", ROCK_COLUMNS, rock),
    }


def write(out: dict, out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, key in (("wells.geojson", "wells"), ("water-tests.json", "water"), ("rock-tests.json", "rock")):
        p = out_dir / name
        p.write_text(json.dumps(out[key], separators=(",", ":"), ensure_ascii=False) + "\n")
        paths.append(p)
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extracted", type=Path, default=EXTRACTED)
    ap.add_argument("--catalog", type=Path, default=CATALOG)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    out = build(args.extracted, _catalog(args.catalog))
    write(out, args.out_dir)
    c = out["wells"]["counts"]
    print(f"{c['features']} sites placed; left out: {sum(c['no_location'].values())} without a location, "
          f"{sum(c['radius_over_limit'].values())} placed less precisely than {MAX_LOCATION_RADIUS_M} m; "
          f"{out['water']['counts']['tests']} water tests, {out['rock']['counts']['tests']} rock tests "
          f"-> {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
