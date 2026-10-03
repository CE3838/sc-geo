"""Ranking and confidence for merging overlapping geologic maps.

Where maps overlap, the winner is the most detailed map (smallest scale
denominator), then the newest, then the one whose mapper was certain of the
unit. Its confidence starts from map scale and the mapper's identity
confidence and is then raised or lowered by how well the other maps covering
the same ground agree (area-weighted), with a small boost when the unit is a
recognized Geolex unit whose age matches. Every input here is a unit record
in the merge schema (see merge/sources.py).
"""

from __future__ import annotations

import re

from model.units import Lexicon, age_overlap, age_range

_SCALE_STEPS = [(24000, 0.95), (62500, 0.9), (100000, 0.85), (250000, 0.7), (500000, 0.55), (1000000, 0.45)]
_SURFICIAL = re.compile(r"sediment(?!ary)|made|human|water|unconsolidated|regolith|residu|alluvi|colluvi|eolian|marsh|peat|"
                        r"fill|sand|gravel|clay|mud|beach|dune", re.I)
_BEDROCK = re.compile(r"rock|granit|metamorph|igneous|gneiss|schist|volcanic|plutonic|intrusive|mylonit", re.I)


def scale_weight(scale: int | None) -> float:
    if not scale:
        return 0.35
    for limit, weight in _SCALE_STEPS:
        if scale <= limit:
            return weight
    return 0.35


def identity_weight(identity: str | None) -> float:
    ic = (identity or "").strip().lower()
    return {"certain": 1.0, "questionable": 0.8}.get(ic, 0.9)


def priority(u: dict) -> tuple:
    """Sort key: the first unit wins."""
    return (u.get("scale") or 10**9, -(u.get("year") or 0), -identity_weight(u.get("identity_confidence")))


def layer(u: dict) -> str:
    """'surficial' for sediments and other unconsolidated material, else 'bedrock' (inferred)."""
    gm = u.get("geomaterial") or ""
    if gm:
        if _BEDROCK.search(gm) and not re.search(r"sediment(?!ary)", gm, re.I):
            return "bedrock"
        if _SURFICIAL.search(gm):
            return "surficial"
    lith = u.get("lith") or ""
    if lith:
        return "surficial" if re.match(r"unconsolidated|water", lith, re.I) else "bedrock"
    rng = age_range(u.get("age"))
    return "surficial" if rng and rng[1] <= 66.0 else "bedrock"


def _cmp(u: dict) -> dict:
    """What to compare: a facies is compared as its formation."""
    return {"name": u.get("formation") or u.get("name"), "age": u.get("age")}


def research_support(u: dict, lex: Lexicon) -> bool:
    entry = lex.resolve(_cmp(u)["name"])
    if not entry:
        return False
    overlap = age_overlap(age_range(u.get("age")), age_range(entry.get("age")))
    return overlap is None or overlap > 0


def is_water(u: dict) -> bool:
    """Water polygons differ between maps by shoreline drawing, not by interpretation."""
    low = lambda k: (u.get(k) or "").strip().lower()
    return (low("name") in ("water", "bodies of water") or low("map_unit") == "water"
            or low("geomaterial").startswith("water") or low("lith") == "water")


def confidence(winner: dict, others: list[tuple[dict, float]], lex: Lexicon) -> dict:
    """Confidence for the winning unit; `others` are (unit, share of the area they cover).

    Water is left out on both sides, and a map counts once however many of
    its polygons lie under the winner."""
    others = [(u, w) for u, w in others if not is_water(u)] if not is_water(winner) else []
    base = scale_weight(winner.get("scale")) * identity_weight(winner.get("identity_confidence"))
    weight = sum(w for _, w in others)
    agreement = (sum(lex.agreement(_cmp(winner), _cmp(u)) * w for u, w in others) / weight) if weight > 0 else None
    value = base * (0.8 + 0.25 * agreement) if agreement is not None else base * 0.92
    supported = research_support(winner, lex)
    if supported:
        value += 0.03
    return {
        "value": round(min(1.0, value), 3),
        "base": round(base, 3),
        "agreement": None if agreement is None else round(agreement, 3),
        "sources": 1 + len({u.get("source") for u, _ in others}),
        "research_support": supported,
    }


def alternatives(winner: dict, others: list[tuple[dict, float]], lex: Lexicon) -> list[dict]:
    """Other maps' interpretations that do not fully agree with the winner."""
    out = []
    for u, w in others:
        if is_water(u) or is_water(winner):
            continue
        a = lex.agreement(_cmp(winner), _cmp(u))
        if a < 1.0:
            out.append({"source": u.get("source"), "name": u.get("name"), "age": u.get("age"),
                        "scale": u.get("scale"), "overlap": round(w, 3), "agreement": a})
    return sorted(out, key=lambda x: -x["overlap"])
