"""A derived NAVD88 value next to every stored elevation whose datum can be resolved.

Elevations are: observation `elevation`, interval `top`/`bottom` when the
observation's `depth_reference` is "elevation", surface `elevation`,
groundwater `head` (unless given relative to land surface), and a section's
`units_along` `top_elevation`/`base_elevation`. The datum comes from the
record's `datum` value (a section's for its units), else from the elevation's
own text ("42 ft above NAVD 88"), else it is not stated. The location for the
NGVD29 grid is the record's `location` (or `coordinates`) as converted by
model/coords.py; for a section, the midpoint of its two ends.

Each conversion is its own StoredValue under `navd88` (extraction_method
"datum_conversion", inferred=True, the elevation's page, confidence times the
inference factor and, when approximate, `approximate_factor`). The value as read
is never changed. Contour labels have no location and are not converted.
"""

from __future__ import annotations

from collections import Counter

from extract import patterns
from model import vdatum
from model.provenance import ExtractionMethod, StoredValue

KEY = "navd88"


def _coords(node) -> tuple[float, float] | None:
    for key in ("coordinates", "location"):
        v = (node or {}).get(key)
        d = v.get("derived_coordinates") if isinstance(v, dict) else None
        if d:
            return d["value"]["lat"], d["value"]["lon"]
    return None


def _datum(record: dict, entry: dict, parent_datum: dict | None = None) -> tuple[str | None, str, int | None]:
    """(datum key, where it came from, page of the datum value)."""
    for d, where in ((record.get("datum"), "datum field"), (parent_datum, "section datum")):
        if isinstance(d, dict) and "value" in d:
            return d.get("normalized") or patterns.vertical_datum(d["value"]) or "unrecognized", where, d.get("page")
    from_text = patterns.vertical_datum(entry.get("value")) if isinstance(entry.get("value"), str) else None
    if from_text:
        return from_text, "value text", entry.get("page")
    return None, "not stated", None


def _clear(node) -> None:
    if isinstance(node, dict):
        node.pop(KEY, None)
        for v in node.values():
            _clear(v)
    elif isinstance(node, list):
        for v in node:
            _clear(v)


def attach_navd88(sections: dict, year: int | None, grid, cfg: dict, inferred_factor: float = 0.8) -> dict:
    """Add (or refresh) `navd88` on every elevation in the stored sections; returns counts."""
    _clear(sections)
    stats = {"converted": 0, "skipped": Counter()}

    def convert(entry, record, location, location_from, parent_datum=None):
        if not isinstance(entry, dict) or "value" not in entry:
            return
        if isinstance(entry.get("normalized"), dict) and entry["normalized"].get("relative_to"):
            stats["skipped"]["relative to land surface; no elevation datum"] += 1
            return
        ft = patterns.elevation_ft(entry["value"], default_unit=entry.get("units"))
        if ft is None:
            stats["skipped"]["elevation not readable as a number with units"] += 1
            return
        datum, datum_from, datum_page = _datum(record, entry, parent_datum)
        lat, lon = location if location else (None, None)
        res, why = vdatum.to_navd88(ft, datum, lat, lon, year, grid, cfg)
        if res is None:
            stats["skipped"][why] += 1
            return
        conf = entry["confidence"] * inferred_factor * (cfg.get("approximate_factor", 0.9) if res["approximate"] else 1)
        sv = StoredValue(value={"min_ft": res["min_ft"], "max_ft": res["max_ft"]}, source_id=entry["source_id"],
                         page=entry["page"], extraction_method=ExtractionMethod.DATUM_CONVERSION,
                         confidence=round(min(1.0, conf), 3), inferred=True, locator=entry.get("locator"))
        entry[KEY] = sv.to_dict() | {k: res[k] for k in ("from_datum", "shift_ft", "conversion", "approximate",
                                                          "assumptions")} | {
            "datum_from": datum_from, "datum_page": datum_page,
            "location_from": location_from if location and res["from_datum"] == "NGVD29" and grid is not None
            else None}
        stats["converted"] += 1

    for rec in sections.get("observations", []):
        here = _coords(rec)
        convert(rec.get("elevation"), rec, here, "location")
        ref = rec.get("depth_reference")
        if isinstance(ref, dict) and ref.get("value") == "elevation":
            for iv in rec.get("intervals", []):
                for key in ("top", "bottom"):
                    convert(iv.get(key), rec, here, "location")
    for rec in sections.get("surfaces", []):
        convert(rec.get("elevation"), rec, _coords(rec), "location")
    for rec in sections.get("groundwater", []):
        convert(rec.get("head"), rec, _coords(rec), "location")
    for rec in sections.get("sections", []):
        ends = [_coords(rec.get(k)) for k in ("start", "end")]
        mid = None
        if all(ends):
            mid = ((ends[0][0] + ends[1][0]) / 2, (ends[0][1] + ends[1][1]) / 2)
        for u in rec.get("units_along", []):
            for key in ("top_elevation", "base_elevation"):
                convert(u.get(key), {}, mid, "section ends (midpoint)", rec.get("datum"))
    stats["skipped"] = dict(stats["skipped"])
    return stats
