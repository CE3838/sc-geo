"""Water tests and rock tests per site, with locations and depths, for the viewer and cross sections.

Reads the stored `water_tests` and `rock_tests` of data/extracted (public catalog records only)
and writes one JSON file, web/data/sites/site-tests.json, that the click callout and the future
cross-section tool can load; merge.package puts it in the data package as data/sites/site-tests.json.
The format is described in extract/README.md ("Site tests export").

A site is one well, boring, core, spring or outcrop of one source document: the tests' `observation`
label (compared without case, spaces or dashes) or, without a label, their printed location. Its
coordinates come from the inferred `derived_coordinates` of the test's own location or else of the
observation with the same label in that document. Nothing is computed that the stored values do not
hold: no coordinates from place names, no units, no elevations from depths, no datum conversions.

Run: python -m merge.site_tests [--out web/data/sites/site-tests.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / "data" / "extracted"
CATALOG = ROOT / "data" / "catalog" / "sc_catalog.json"
OUT = ROOT / "web" / "data" / "sites" / "site-tests.json"
TESTS = ("water_tests", "rock_tests")
CITE_KEYS = ("value", "page", "quote", "confidence", "inferred", "verification", "locator")
NOTES = ("Public data only, read from published documents. Every value keeps its source, page and verbatim "
         "quote; coordinates, normalized names and test types are inferred and flagged. Units are as printed, "
         "never guessed. Each source keeps its own terms; cite it when reusing its data. "
         "Provided as is, without warranty of any kind.")


def site_key(label) -> str:
    """A label compared without case, spaces or dashes ("DOR 120" and "dor-120" are DOR120)."""
    return re.sub(r"[^A-Z0-9]", "", str(label or "").upper())


def _v(rec: dict, field: str):
    x = rec.get(field)
    return x if isinstance(x, dict) and "page" in x else None


def _value(rec: dict, field: str):
    x = _v(rec, field)
    return x.get("value") if x else None


def _cite(x: dict) -> dict:
    return {k: x.get(k) for k in CITE_KEYS}


def _location(test: dict, obs: dict | None) -> dict | None:
    for origin, rec in (("test", test), ("observation", obs or {})):
        loc = _v(rec, "location")
        d = loc and loc.get("derived_coordinates")
        if d:
            return {"lat": d["value"]["lat"], "lon": d["value"]["lon"], "as_printed": loc.get("value"),
                    "from": origin, "page": loc.get("page"), "inferred": True, "confidence": d.get("confidence"),
                    "conversion": d.get("conversion"), "datum": d.get("datum"),
                    "approximate": d.get("approximate"), "assumptions": d.get("assumptions")}
    for origin, rec in (("test", test), ("observation", obs or {})):
        loc = _v(rec, "location")
        if loc:
            return {"lat": None, "lon": None, "as_printed": loc.get("value"), "from": origin, "page": loc.get("page"),
                    "inferred": False}
    return None


def _elevation(obs: dict | None) -> dict | None:
    el = _v(obs or {}, "elevation")
    if not el:
        return None
    norm = el.get("normalized") or {}
    datum = _v(obs, "datum")
    out = {"as_printed": el.get("value"), "units": el.get("units"), "ft": norm.get("min_ft"),
           "datum": (datum.get("normalized") if datum else None), "datum_as_printed": datum and datum.get("value"),
           "page": el.get("page"), "confidence": el.get("confidence")}
    if el.get("navd88"):          # added by the NAVD 88 conversion when it runs (extract/elevations.py)
        out["navd88"] = el["navd88"]
    return out


def _depth(test: dict, obs: dict | None) -> dict | None:
    """Top and bottom in feet as stored (normalized lengths), with what they are measured from."""
    ref = _value(test, "depth_reference") or _value(obs or {}, "depth_reference")
    top, bottom, one = (_v(test, k) for k in ("top", "bottom", "depth"))
    t = (top or one or {}).get("normalized") or {}
    b = (bottom or one or {}).get("normalized") or {}
    if not t and not b:
        return None
    if ref == "elevation":
        from extract import patterns  # elevations keep their sign
        t = patterns.elevation_ft((top or one)["value"], (top or one).get("units")) if (top or one) else {}
        b = patterns.elevation_ft((bottom or one)["value"], (bottom or one).get("units")) if (bottom or one) else {}
        t, b = t or {}, b or {}
    return {"top_ft": t.get("min_ft", t.get("max_ft")), "bottom_ft": b.get("max_ft", b.get("min_ft")),
            "reference": ref}


def _test_entry(section: str, test: dict, obs: dict | None, sid: str) -> dict:
    fields = {k: _cite(x) for k in test if (x := _v(test, k))}
    val = _v(test, "value") or {}
    parsed = val.get("normalized") or {}
    units = _value(test, "units") or val.get("units")
    q = _v(test, "qualifier")
    entry = {"source_id": sid, "pages": sorted({x["page"] for x in fields.values()})}
    if section == "water_tests":
        p = _v(test, "parameter") or {}
        n = p.get("normalized") or {}
        entry["parameter"] = {"as_printed": p.get("value"), "name": n.get("name"), "category": n.get("category"),
                              "inferred": True if n else False}
    else:
        t = _v(test, "test_type") or {}
        n = t.get("normalized") or {}
        entry["test_type"] = {"as_printed": t.get("value"), "type": n.get("type"), "inferred": True if n else False}
    entry["value"] = {"as_printed": val.get("value"),
                      **({"min": parsed["min"], "max": parsed["max"]} if "min" in parsed
                         else {"number": parsed.get("number")}),
                      "qualifier": (q.get("normalized") if q else None) or parsed.get("qualifier"),
                      "units": units}
    d = _v(test, "date")
    entry["date"] = (d.get("normalized") or d.get("value")) if d else None
    entry["depth"] = _depth(test, obs)
    for k in ("sample_id", "aquifer", "unit", "fraction", "method", "lab", "rock_type",
              "specimen_dimensions", "specimen_condition", "confining_pressure", "failure_mode", "standard",
              "source_table"):
        if k in fields:
            entry[k] = fields[k]["value"]
    if section == "rock_tests" and "parameter" in fields:
        entry["parameter"] = fields["parameter"]["value"]
    entry["fields"] = fields
    return entry


def _observations(doc: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for o in doc.get("observations", []):
        key = site_key(_value(o, "label"))
        if key:
            out.setdefault(key, []).append(o)
    return out


def _catalog_ids(path: Path = CATALOG) -> set[str]:
    return {r["id"] for r in json.loads(Path(path).read_text())}


def build(extracted_dir: Path = EXTRACTED, catalog: dict | set | None = None) -> dict:
    ids = set(catalog) if catalog is not None else _catalog_ids()
    sites: dict[tuple, dict] = {}
    sources: dict[str, dict] = {}
    for path in sorted(Path(extracted_dir).glob("*.json")):
        doc = json.loads(path.read_text())
        sid = doc.get("source_id")
        if sid not in ids or not any(doc.get(s) for s in TESTS):
            continue
        obs_by_label = _observations(doc)
        for section in TESTS:
            for test in doc.get(section, []):
                label = _value(test, "observation")
                key = site_key(label)
                matches = obs_by_label.get(key, []) if key else []
                obs = matches[0] if matches else None
                loc_text = _value(test, "location")
                skey = (sid, key or f"@{loc_text or ''}")
                site = sites.get(skey)
                if site is None:
                    where = key or (f"location:{site_key(loc_text)}" if loc_text else "unplaced")
                    site = sites[skey] = {
                        "id": f"{sid}#{where}", "source_id": sid, "label": _value(obs, "label") if obs else label, "site_key": key or None,
                        "kind": test.get("kind") or (obs or {}).get("kind"),
                        "observation_matches": len(matches),
                        "location": _location(test, obs), "elevation": _elevation(obs),
                        "total_depth": _value(obs or {}, "total_depth"),
                        "water_tests": [], "rock_tests": []}
                elif site["location"] is None or site["location"].get("lat") is None:
                    better = _location(test, obs)
                    if better and better.get("lat") is not None:
                        site["location"] = better
                site[section].append(_test_entry(section, test, obs, sid))
                sources[sid] = {k: doc.get(k) for k in ("citation", "title", "year", "publisher")}
    out_sites = list(sites.values())
    return {
        "format": "sc-geo site tests", "version": 1,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": NOTES,
        "counts": {"sites": len(out_sites), "water_tests": sum(len(s["water_tests"]) for s in out_sites),
                   "rock_tests": sum(len(s["rock_tests"]) for s in out_sites), "sources": len(sources)},
        "sources": sources,
        "sites": out_sites,
    }


def write(doc: dict, out: Path = OUT) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extracted", type=Path, default=EXTRACTED)
    ap.add_argument("--catalog", type=Path, default=CATALOG)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    doc = build(args.extracted, _catalog_ids(args.catalog))
    write(doc, args.out)
    c = doc["counts"]
    print(f"{c['sites']} sites, {c['water_tests']} water tests, {c['rock_tests']} rock tests -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
