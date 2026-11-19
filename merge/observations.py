"""Check extracted point observations against the merged geologic layers (a report; the map is not changed).

Wells, borings, auger holes, cores and outcrops read from documents (data/extracted, `observations`) are
placed by their converted coordinate (`location.derived_coordinates`), or by parsing the printed location
with model.coords when there is none. Each gets:

- the merged unit it falls in, per layer (surficial, bedrock);
- the unit the source names at that point: the shallowest interval with a formal (named) unit whose top
  is no deeper than SURFACE_FT, or, for an outcrop, any interval with a formal unit (outcrops give no depth);
- a status:
  * `agree`: the named unit and a merged unit at the point resolve to the same named unit
    (model.units.Lexicon, abandoned names followed);
  * `near_contact`: they differ, but the point lies within its location uncertainty (radius from the
    printed precision, model.coords.location_radius) of the merged polygon's edge;
  * `disagree`: they differ farther from any edge (compared with the surficial unit where there is one,
    else the bedrock unit);
  * `not_comparable`: a unit is named, but the merged unit there is informal (no geographic name);
  * `no_unit_named`: the source names no formal unit at the surface;
  * `outside`: no merged polygon holds the point.

Every record cites its source_id and page, and keeps the location's own `inferred` flag and uncertainty.
Nothing here changes a polygon or its confidence. See docs/merge_extracted.md.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from shapely import affinity
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from model import coords
from model.units import Lexicon, name_key

SURFACE_FT = 10  # a named unit counts as the unit at the surface when its interval starts this shallow
M_PER_DEG = 111_195  # metres per degree of latitude (mean), for distances to a polygon edge
STATUSES = ("agree", "disagree", "near_contact", "no_unit_named", "not_comparable", "outside")
LAYERS = ("surficial", "bedrock")


def _value(x):
    return x.get("value") if isinstance(x, dict) else x


def _top_ft(interval: dict):
    top = interval.get("top")
    if not isinstance(top, dict):
        return None
    norm = top.get("normalized") or {}
    v = norm.get("min_ft")
    return v if isinstance(v, (int, float)) else None


def _named_unit(o: dict) -> tuple[dict | None, float | None]:
    """The formal unit the source names at the surface, as stored, and its interval top (ft)."""
    outcrop = _value(o.get("kind")) == "outcrop"
    best = None
    for iv in o.get("intervals") or []:
        unit = iv.get("unit")
        if not isinstance(unit, dict) or not name_key(str(unit.get("value") or ""))[0]:
            continue
        top = _top_ft(iv)
        if top is None and not outcrop:
            continue
        if top is not None and top > SURFACE_FT:
            continue
        if best is None or (top or 0) < (best[1] or 0):
            best = (unit, top)
    return best if best else (None, None)


def points(docs: list[dict], catalog: list[dict]) -> list[dict]:
    """Located observations with the unit each source names at the surface."""
    bboxes = {r["id"]: r.get("bbox") for r in catalog}
    out = []
    for d in docs:
        sid = d.get("source_id")
        for i, o in enumerate(d.get("observations") or []):
            loc = o.get("location")
            if not isinstance(loc, dict):
                continue
            dc = loc.get("derived_coordinates")
            if isinstance(dc, dict) and isinstance(dc.get("value"), dict):
                lat, lon = dc["value"].get("lat"), dc["value"].get("lon")
                inferred = bool(dc.get("inferred", True) or loc.get("inferred"))
                datum_assumed = bool(dc.get("datum_assumed"))
            else:
                c = coords.parse(loc.get("value"))
                if c is None:
                    continue
                lat, lon, inferred, datum_assumed = c["lat"], c["lon"], True, bool(c.get("datum_assumed"))
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue
            rad = coords.location_radius(loc.get("value"), assume_state_plane_nad83=datum_assumed,
                                         bbox=bboxes.get(sid)) if inferred else None
            unit, top = _named_unit(o)
            out.append({
                "id": f"{sid}#observations[{i}]",
                "source_id": loc.get("source_id") or sid,
                "page": loc.get("page"),
                "citation": d.get("citation") or d.get("title"),
                "kind": _value(o.get("kind")),
                "label": _value(o.get("label")),
                "lat": lat,
                "lon": lon,
                "location_inferred": inferred,
                "radius_m": rad["radius_m"] if rad else None,
                "radius_basis": rad["basis"] if rad else (["exact coordinates"] if not inferred
                                                          else ["precision not readable"]),
                "named_unit": unit,
                "named_unit_top_ft": top,
            })
    return out


def _edge_m(geom, pt: Point) -> float:
    """Distance (m) from a point inside `geom` to its edge, longitudes scaled to the point's latitude."""
    scaled = affinity.scale(geom.boundary, xfact=math.cos(math.radians(pt.y)), yfact=1.0, origin=pt)
    return scaled.distance(pt) * M_PER_DEG


def classify(records: list[dict], merged: dict[str, list[dict]], lex: Lexicon) -> list[dict]:
    """Records with `merged` (per layer: source, map_unit, name, canonical), `status` and details."""
    trees = {}
    for layer in LAYERS:
        feats = merged.get(layer) or []
        geoms = [shape(f["geometry"]) for f in feats]
        trees[layer] = (STRtree(geoms) if geoms else None, geoms, feats)
    out = []
    for r in records:
        pt = Point(r["lon"], r["lat"])
        hits = {}
        for layer, (tree, geoms, feats) in trees.items():
            if tree is None:
                continue
            for j in tree.query(pt, predicate="intersects"):
                hits[layer] = (geoms[j], feats[j]["properties"])
                break
        rec = {**r, "merged": {}, "matched_layer": None, "contact_distance_m": None}
        for layer, (_, p) in hits.items():
            canon = p.get("canonical") or lex.canonical(p.get("formation") or p.get("name"))
            rec["merged"][layer] = {"source": p.get("source"), "map_unit": p.get("map_unit"), "name": p.get("name"),
                                    "canonical": canon}
        named = lex.canonical(r["named_unit"]["value"]) if r.get("named_unit") else None
        if not hits:
            rec["status"] = "outside"
        elif not named:
            rec["status"] = "no_unit_named"
        else:
            match = next((layer for layer in LAYERS if layer in rec["merged"]
                          and (rec["merged"][layer]["canonical"] or "").lower() == named.lower()), None)
            primary = "surficial" if "surficial" in hits else "bedrock"
            if match:
                rec["status"], rec["matched_layer"] = "agree", match
            elif not rec["merged"][primary]["canonical"]:
                rec["status"] = "not_comparable"
            else:
                dist = _edge_m(hits[primary][0], pt)
                rec["contact_distance_m"] = round(dist, 1)
                near = rec["radius_m"] is not None and dist <= rec["radius_m"]
                rec["status"] = "near_contact" if near else "disagree"
        rec["named_canonical"] = named
        out.append(rec)
    return out


def report(records: list[dict]) -> dict:
    summary = {s: sum(1 for r in records if r["status"] == s) for s in STATUSES}
    summary["total"] = len(records)
    return {
        "about": "Extracted point observations placed on the merged layers (merge/observations.py): the merged "
                 "unit at each point next to the unit the source names there. A report only; the map and its "
                 "confidence are not changed. Locations converted from printed coordinates are inferred.",
        "surface_ft": SURFACE_FT,
        "summary": summary,
        "records": records,
    }


def write(rep: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep, separators=(",", ":")))
    return path
