"""Attach unit descriptions read from documents (data/extracted) to merged map polygons.

A merged polygon (merge/overlay.py) carries the winning GIS map's unit. Map
explanations and reports read by extract/ describe units in words: name, age,
lithology, thickness, and so on, each a StoredValue with its page and quote.
This module links the two, without changing any polygon's geometry, unit or
confidence:

- `index` turns every named extracted unit into an entry with its document's
  citation, scale, year and footprint (the catalog bounding box), and its
  fields as stored (provenance kept as is).
- `attach` gives every polygon an `extracted` list of links (entry id, how it
  matched, whether the link is inferred), most detailed
  map first, then newest. An entry matches when
  * its unit name and the polygon's unit name resolve to the same named unit
    (model.units.Lexicon, abandoned names followed); the link is an inference
    (`match.inferred` true), or
  * it comes from the polygon's own map and its map symbol equals the
    polygon's map unit (the map's own printed explanation; not inferred),
  and its document's footprint touches the polygon's bounding box.
  Informal names (no geographic name) match by symbol only.

The entries go in a shared table (id -> entry), so polygons of one unit do not
repeat the text. See docs/merge_extracted.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from model.provenance import StoredValue
from model.units import Lexicon

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED = ROOT / "data" / "extracted"

# Unit fields carried over from extract/schema.json (map_symbol is used for matching and kept too).
FIELDS = ("name", "map_symbol", "rank", "group", "age", "description", "lithology", "thickness", "contacts",
          "depositional_environment", "fossils")


def load(directory: Path = EXTRACTED) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(Path(directory).glob("*.json"))]


def _value(field) -> dict | None:
    """A stored field (StoredValue dict plus quote etc.), or None when absent or not a valid StoredValue."""
    if not isinstance(field, dict) or field.get("value") in (None, ""):
        return None
    try:
        StoredValue.from_dict(field)
    except (KeyError, ValueError):
        return None
    return field


def index(docs: list[dict], catalog: list[dict], lex: Lexicon) -> list[dict]:
    """Named extracted units of documents that have a catalog footprint."""
    bboxes = {r["id"]: r["bbox"] for r in catalog if r.get("bbox") and len(r["bbox"]) == 4}
    out = []
    for d in docs:
        sid = d.get("source_id")
        bbox = bboxes.get(sid)
        if not bbox:
            continue
        for i, unit in enumerate(d.get("units") or []):
            fields = {k: v for k in FIELDS if (v := _value(unit.get(k))) is not None}
            if "name" not in fields:
                continue
            sym = fields.get("map_symbol", {}).get("value")
            out.append({
                "id": f"{sid}#units[{i}]",
                "source_id": sid,
                "citation": d.get("citation") or d.get("title"),
                "scale": d.get("scale"),
                "year": d.get("year"),
                "bbox": [float(v) for v in bbox],
                "canonical": lex.canonical(fields["name"]["value"]) if _named(fields["name"]["value"]) else None,
                "symbol": str(sym).strip() if sym is not None else None,
                "fields": fields,
            })
    return out


def _named(name: str) -> bool:
    from model.units import name_key
    return name_key(name)[0] is not None


def _coords(c):
    if c and isinstance(c[0], (int, float)):
        yield c
    else:
        for x in c:
            yield from _coords(x)


def bbox(geometry: dict) -> list[float]:
    pts = list(_coords(geometry["coordinates"]))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _touch(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _rank(e: dict) -> tuple:
    return (e.get("scale") or 10**12, -(e.get("year") or 0), e["id"])


def attach(features: list[dict], entries: list[dict], lex: Lexicon) -> tuple[list[dict], dict]:
    """Copies of `features` with `properties.extracted` (links to entries) and the table of matched entries."""
    by_name: dict[str, list[dict]] = {}
    by_symbol: dict[tuple, list[dict]] = {}
    for e in entries:
        if e["canonical"]:
            by_name.setdefault(e["canonical"].lower(), []).append(e)
        if e["symbol"]:
            by_symbol.setdefault((e["source_id"], e["symbol"]), []).append(e)
    by_id = {e["id"]: e for e in entries}
    out, table = [], {}
    for f in features:
        f = {**f, "properties": dict(f["properties"])}
        p = f["properties"]
        box = bbox(f["geometry"])
        canon = p.get("canonical") or lex.canonical(p.get("formation") or p.get("name"))
        hits: dict[str, dict] = {}
        for e in by_symbol.get((p.get("source"), str(p.get("map_unit") or "").strip()), []):
            if _touch(box, e["bbox"]):
                hits[e["id"]] = {"by": "symbol", "value": e["symbol"], "inferred": False}
        for e in by_name.get(canon.lower(), []) if canon else []:
            if e["id"] not in hits and _touch(box, e["bbox"]):
                hits[e["id"]] = {"by": "name", "value": e["canonical"], "inferred": True}
        ranked = sorted((by_id[i] for i in hits), key=_rank)
        for e in ranked:
            table.setdefault(e["id"], {k: v for k, v in e.items() if k not in ("canonical", "symbol")})
        p["extracted"] = [{"id": e["id"], **hits[e["id"]]} for e in ranked]
        out.append(f)
    return out, table
