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

A site with no such coordinate (or only one placed less precisely) may borrow one printed for the same well
elsewhere: another document's well table or observation, or the same document's location table on another
page, matched only on an exact, normalized well ID (merge.well_ids; never on a name or place description).
The borrowed coordinate is a separate inferred value (StoredValue, extraction_method "inference") that cites
both the site's label (source, page, quote) and the coordinate's source (source, page, quote), noted "located
by well ID match"; the one-mile rule applies to its own printed precision. When precise coordinates for the
same ID lie more than MAX_LOCATION_RADIUS_M apart, the site is not placed and is listed in
data/review/well_id_conflicts.json.
Exact coordinates that are not inferred would be kept as they are. The full list, placed or not, stays in
site-tests.json (merge.site_tests). The format is in extract/README.md ("Known wells and tests for the map").

Run: python -m merge.wells [--out-dir web/data/sites] [--conflicts data/review/well_id_conflicts.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from merge import site_tests, well_ids
from merge.site_tests import _test_entry, _v, _value, site_key, tests_of
from model import coords
from model.provenance import ExtractionMethod, StoredValue

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = site_tests.EXTRACTED
CATALOG = site_tests.CATALOG
OUT_DIR = ROOT / "web" / "data" / "sites"
CONFLICTS = ROOT / "data" / "review" / "well_id_conflicts.json"
MATCH_NOTE = "located by well ID match"

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
    "ls": "source id of the location when it was borrowed from another record by well ID match (see sources)",
    "mt": "well ID match: note, id (matched key), m method, i inferred, c confidence, test (s, p, q of the "
          "site's label), coord (s, p, q, lc of the location; l, lp, lq its label), value (the stored value)",
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


def _radius(loc: dict, d: dict, bbox) -> tuple[float, dict]:
    """(rank, radius) of one derived coordinate: exact coordinates rank 0, unreadable precision last."""
    if not d.get("inferred", True):
        rad = {"radius_m": None, "basis": ["exact coordinates"]}
    else:
        rad = coords.location_radius(loc.get("value"), assume_state_plane_nad83=bool(d.get("datum_assumed")),
                                     bbox=bbox) or {"radius_m": None, "basis": ["precision not readable"]}
    rank = rad["radius_m"] if rad["radius_m"] is not None else (0 if not d.get("inferred", True) else 1e12)
    return rank, rad


def _within_limit(d: dict, rad: dict) -> bool:
    return not d.get("inferred", True) or (rad["radius_m"] is not None and rad["radius_m"] <= MAX_LOCATION_RADIUS_M)


def _placement(records: list[dict], bbox) -> tuple[dict, dict, dict] | None:
    """(location value, derived coordinate, radius) of the best-placed record (smallest radius); None if none."""
    best = None
    for rec in records:
        loc = _v(rec, "location")
        d = loc and loc.get("derived_coordinates")
        if not d:
            continue
        rank, rad = _radius(loc, d, bbox)
        if best is None or rank < best[0]:
            best = (rank, loc, d, rad)
    return best[1:] if best else None


def _id_index(docs: list[dict], catalog: dict) -> dict[str, list[dict]]:
    """Precisely placed labelled records of all documents, by well ID key (merge.well_ids).

    Shared keys (county well numbers, USGS site numbers) are looked up from any document; a document's own
    keys ("<source id>|id:<ID>") only from that document."""
    index: dict[str, list[dict]] = {}
    for doc in docs:
        sid = doc.get("source_id")
        bbox = catalog[sid].get("bbox")
        recs = [(o, "label") for o in doc.get("observations", [])]
        recs += [(t, "observation") for sec in site_tests.TESTS for t in tests_of(doc, sec)]
        for rec, field in recs:
            label = _v(rec, field)
            loc = _v(rec, "location")
            d = loc and loc.get("derived_coordinates")
            if not label or not d or not isinstance(d.get("value"), dict):
                continue
            rank, rad = _radius(loc, d, bbox)
            if not _within_limit(d, rad):
                continue
            entry = {"sid": sid, "key": site_key(label.get("value")), "label": label, "loc": loc, "d": d,
                     "rad": rad, "rank": rank}
            keys = set(well_ids.shared_keys(label))
            local = well_ids.local_key(label)
            if local:
                keys.add(f"{sid}|{local}")
            for k in keys:
                index.setdefault(k, []).append(entry)
    return index


def _borrow(sid: str, site_key_: str | None, labels: list[dict], index: dict) -> dict | None:
    """Coordinates printed elsewhere for the same well ID: {"best", "candidates", "key", "label"} or None."""
    found: dict[tuple, tuple[str, dict]] = {}
    label_of: dict[str, dict] = {}
    for label in labels:
        keys = set(well_ids.shared_keys(label))
        local = well_ids.local_key(label)
        if local:
            keys.add(f"{sid}|{local}")
        for k in sorted(keys):
            label_of.setdefault(k, label)
            for e in index.get(k, []):
                if e["sid"] == sid and site_key_ and e["key"] == site_key_:
                    continue        # the site's own record, already tried
                v = e["d"]["value"]
                ident = (e["sid"], e["loc"].get("page"), e["loc"].get("quote"), v.get("lat"), v.get("lon"))
                if ident not in found or k < found[ident][0]:
                    found[ident] = (k, e)
    if not found:
        return None
    cands = sorted(found.values(), key=lambda ke: (ke[1]["rank"], ke[1]["sid"], ke[1]["loc"].get("page") or 0))
    key, best = cands[0]
    sep = max((coords._dist_m(a["d"]["value"]["lat"], a["d"]["value"]["lon"],
                              b["d"]["value"]["lat"], b["d"]["value"]["lon"])
               for i, (_, a) in enumerate(cands) for _, b in cands[i + 1:]), default=0.0)
    return {"best": best, "key": key.split("|", 1)[-1], "label": label_of[key], "candidates": cands,
            "max_separation_m": round(sep)}


def _match_props(sid: str, m: dict) -> dict:
    """Feature properties of a site placed by a borrowed coordinate, with the stored inferred value."""
    e, label = m["best"], m["label"]
    loc, d = e["loc"], e["d"]
    conf = min(float(d.get("confidence") or 0.0), float(label.get("confidence") or 0.0))
    value = StoredValue(value={"lat": d["value"]["lat"], "lon": d["value"]["lon"]}, source_id=e["sid"],
                        page=d.get("page") or loc.get("page"), extraction_method=ExtractionMethod.INFERENCE,
                        confidence=round(conf, 3), inferred=True, locator=loc.get("locator"))
    test = {"s": sid, "p": label.get("page"), "q": label.get("quote")}
    coord = {"s": e["sid"], "p": loc.get("page"), "q": loc.get("quote"), "lc": loc.get("locator"),
             "l": e["label"].get("value"), "lp": e["label"].get("page"), "lq": e["label"].get("quote")}
    return {"p": loc.get("page"), "q": loc.get("quote"), "lc": loc.get("locator"), "loc": loc.get("value"),
            "ls": e["sid"], "ci": 1, "cf": value.confidence, "d": d.get("datum"),
            "a": list(d.get("assumptions") or []) + [MATCH_NOTE], "r": e["rad"]["radius_m"],
            "mt": {"note": MATCH_NOTE, "id": m["key"], "m": value.extraction_method.value, "i": 1,
                   "c": value.confidence, "test": test, "coord": coord,
                   "value": {**value.to_dict(), "note": MATCH_NOTE, "cites": [
                       {"source_id": sid, "page": test["p"], "quote": test["q"]},
                       {"source_id": e["sid"], "page": coord["p"], "quote": coord["q"]}]}}}


def _conflict(site_id: str, sid: str, m: dict) -> dict:
    label = m["label"]
    return {"well_id": m["key"], "site": site_id, "label": label.get("value"),
            "test": {"source_id": sid, "page": label.get("page"), "quote": label.get("quote")},
            "coordinates": [{"source_id": e["sid"], "label": e["label"].get("value"),
                             "page": e["loc"].get("page"), "quote": e["loc"].get("quote"),
                             "locator": e["loc"].get("locator"), "location": e["loc"].get("value"),
                             "lat": e["d"]["value"]["lat"], "lon": e["d"]["value"]["lon"],
                             "radius_m": e["rad"]["radius_m"], "matched_on": k.split("|", 1)[-1]}
                            for k, e in m["candidates"]],
            "max_separation_m": m["max_separation_m"]}


CONFLICTS_ABOUT = ("Sites of the documents whose well ID (merge.well_ids) matches records elsewhere whose printed "
                   f"coordinates lie more than {MAX_LOCATION_RADIUS_M} m apart. They are not placed on the map "
                   "until a reviewer decides which location is right. Written by python -m merge.wells.")


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
    features, water, rock, sources, conflicts = [], {}, {}, {}, []
    kept, no_loc, too_far = Counter(), Counter(), Counter()
    n_match = n_conflict = 0
    docs = [d for d in (json.loads(p.read_text()) for p in sorted(Path(extracted_dir).glob("*.json")))
            if d.get("source_id") in catalog]
    by_sid = {d["source_id"]: d for d in docs}
    index = _id_index(docs, catalog)
    for doc in docs:
        sid = doc.get("source_id")
        rec = catalog[sid]
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
            matched = None
            if place is None or not _within_limit(place[1], place[2]):
                labels = [x for x in [_v(t, "observation") for _, t in s["tests"]] + [_v(o, "label") for o in obs]
                          if x]
                m = _borrow(sid, s["key"], labels, index)
                if m and m["max_separation_m"] > MAX_LOCATION_RADIUS_M:
                    conflicts.append(_conflict(s["id"], sid, m))
                    n_conflict += 1
                    continue
                if m:
                    matched = _match_props(sid, m)
                    place = (m["best"]["loc"], m["best"]["d"], m["best"]["rad"])
            if place is None:
                no_loc[kind] += 1
                continue
            loc, d, rad = place
            inferred = bool(d.get("inferred", True))
            if inferred and (rad["radius_m"] is None or rad["radius_m"] > MAX_LOCATION_RADIUS_M):
                too_far[kind] += 1
                continue
            kept[kind] += 1
            n_match += bool(matched)
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
            if matched:
                props |= matched
                ls = matched["ls"]
                sources[ls] = _source(catalog[ls], by_sid[ls])
            props = {k: v for k, v in props.items() if v is not None or k in ("r", "d")}
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [
                round(d["value"]["lon"], 6), round(d["value"]["lat"], 6)]}, "properties": props})
            if w_rows:
                water[s["id"]] = {"label": label, "source_id": sid, "rows": w_rows}
            if r_rows:
                rock[s["id"]] = {"label": label, "source_id": sid, "rows": r_rows}
            sources[sid] = _source(rec, doc)
    counts = {"features": len(features), "kept": dict(kept), "no_location": dict(no_loc),
              "radius_over_limit": dict(too_far), "id_match": n_match, "id_conflict": n_conflict}
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
        "conflicts": {"format": "sc-geo well ID conflicts", "version": 1, "about": CONFLICTS_ABOUT,
                      "max_location_radius_m": MAX_LOCATION_RADIUS_M, "count": len(conflicts),
                      "items": sorted(conflicts, key=lambda c: c["site"])},
    }


def write(out: dict, out_dir: Path = OUT_DIR, conflicts: Path | None = CONFLICTS) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, key in (("wells.geojson", "wells"), ("water-tests.json", "water"), ("rock-tests.json", "rock")):
        p = out_dir / name
        p.write_text(json.dumps(out[key], separators=(",", ":"), ensure_ascii=False) + "\n")
        paths.append(p)
    if conflicts is not None:
        conflicts = Path(conflicts)
        conflicts.parent.mkdir(parents=True, exist_ok=True)
        conflicts.write_text(json.dumps(out["conflicts"], indent=1, ensure_ascii=False) + "\n")
        paths.append(conflicts)
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extracted", type=Path, default=EXTRACTED)
    ap.add_argument("--catalog", type=Path, default=CATALOG)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--conflicts", type=Path, default=CONFLICTS, help="well ID conflicts for review")
    args = ap.parse_args(argv)
    out = build(args.extracted, _catalog(args.catalog))
    write(out, args.out_dir, args.conflicts)
    c = out["wells"]["counts"]
    print(f"{c['features']} sites placed; left out: {sum(c['no_location'].values())} without a location, "
          f"{sum(c['radius_over_limit'].values())} placed less precisely than {MAX_LOCATION_RADIUS_M} m, "
          f"{c['id_conflict']} with conflicting coordinates for their well ID; {c['id_match']} placed by well ID "
          "match; "
          f"{out['water']['counts']['tests']} water tests, {out['rock']['counts']['tests']} rock tests "
          f"-> {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
