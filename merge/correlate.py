"""Correlate units that different maps name differently (config/unit_correlations.json).

Where a detailed map ends and a coarser one fills in, the same deposit can
carry two names, for example the 1:24,000 maps' "Alluvium" and the
1:500,000 SGMC's "Alluvial Valley Swamp" on the same valley floor. Each
correlation lists the member units (source and map symbol) and the name, age
and GeoMaterial they share, citing the unit it follows (`basis`) and why.

`apply` gives each member that name, age and GeoMaterial before the overlay,
so both sides draw, colour and score alike. The map symbol stays as mapped,
the mapped values are kept in `as_mapped`, the correlation in `correlation`,
and every changed field is listed in `inferred_fields` (CLAUDE.md rule 2).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from merge import score
from model.units import age_range

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "unit_correlations.json"


def load(path: Path = CONFIG) -> list[dict]:
    return json.loads(Path(path).read_text())["correlations"] if Path(path).exists() else []


def apply(features: list[dict], table: list[dict]) -> list[dict]:
    """Features with every correlated member renamed; others are returned as they are.

    A unit is a member when its source and map symbol are listed in `members`,
    or its name (any capitals) is in `names` on any map. An entry without an
    age or GeoMaterial renames only and keeps the member's own.
    """
    by_member = {(m["source"], m["map_unit"]): c for c in table for m in c.get("members", [])}
    by_name = {n.strip().lower(): c for c in table for n in c.get("names", [])}
    if not by_member and not by_name:
        return features
    out = []
    for f in features:
        p = f["properties"]
        c = by_member.get((p.get("source"), p.get("map_unit"))) or by_name.get((p.get("name") or "").strip().lower())
        if c is None:
            out.append(f)
            continue
        f = copy.deepcopy(f)
        p = f["properties"]
        p["as_mapped"] = {k: p.get(k) for k in ("name", "age", "age_ma", "geomaterial")}
        changed = {"name", "unit_name"}
        p.update(name=c["name"], unit_name=c["name"])
        if c.get("age"):
            rng = age_range(c["age"])
            p.update(age=c["age"], age_ma=list(rng) if rng else None)
            changed |= {"age", "age_ma"}
        if c.get("geomaterial"):
            p["geomaterial"] = c["geomaterial"]
            changed.add("geomaterial")
        p["correlation"] = {"name": c["name"], "basis": c.get("basis"), "reason": c["reason"], "inferred": True}
        p["inferred_fields"] = sorted(set(p.get("inferred_fields") or []) | changed)
        p["layer"] = score.layer(p)
        out.append(f)
    return out
