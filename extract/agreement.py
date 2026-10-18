"""Independent sources that agree on a surface raise each other's confidence.

    python -m extract.agreement            # dry run over data/extracted: report pairs, write nothing
    python -m extract.agreement --write    # after ingest: record agreements in the extracted files

A *surface point* is a stored `surfaces[i]` with an `elevation` that has a
derived NAVD88 value (extract/elevations.py), a location converted by
model/coords.py, a `unit` and a `boundary` (top or base). Two points pair when
they come from different sources (`source_id`), name the same unit (Geolex
name when resolved) and boundary, lie within `distance_ft` of each other, and
at least one was `measured` (a boring, well or outcrop): two contour maps
agreeing with each other prove less. A pair agrees when the NAVD88 elevations
differ by at most the tolerance: `unit_tolerance_ft[unit]` or `tolerance_ft`,
plus `approximate_extra_ft` when either NAVD88 value is approximate
(config/extract.json `agreement`).

Each value with k agreeing independent sources gets

    confidence = max(c, min(cap, 1 - (1 - c) * (1 - boost) ** k))

from its ingest confidence c (kept in `agreement.confidence_before`); its
NAVD88 value is raised the same way from its own confidence (kept in its
`confidence_before_agreement`; extract/elevations.py rebuilds it from the
ingest confidence, so re-normalizing never compounds a boost). The pairs are
recorded as provenance (`agrees_with`, `disagrees_with`: source, path, page,
elevation difference, distance). A disagreeing value is never dropped or
lowered: it is listed as an alternative on both sides. Re-running is
idempotent, and a point whose partners are gone returns to its ingest
confidence. Re-ingesting a document resets its confidences, so run this after
ingest.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

from extract import ingest
from extract.renormalize import dumps
from model import coords

CONFIG: dict = ingest.CONFIG["agreement"]
FORMULA = "max(c, min(cap, 1 - (1 - c) * (1 - boost) ** k))"


def boosted(c: float, k: int, cfg: dict = CONFIG) -> float:
    if k <= 0:
        return c
    return max(c, round(min(cfg["cap"], 1 - (1 - c) * (1 - cfg["boost"]) ** k), 3))


def _reset(doc: dict) -> None:
    for rec in doc.get("surfaces", []):
        el = rec.get("elevation")
        if isinstance(el, dict) and "agreement" in el:
            ag = el.pop("agreement")
            el["confidence"] = ag["confidence_before"]
        nav = el.get("navd88") if isinstance(el, dict) else None
        if isinstance(nav, dict) and "confidence_before_agreement" in nav:  # absent when elevations rebuilt it
            nav["confidence"] = nav.pop("confidence_before_agreement")


def _value(rec: dict, key: str):
    v = rec.get(key)
    return v.get("value") if isinstance(v, dict) else None


def _points(docs: dict) -> list[dict]:
    pts = []
    for key, doc in docs.items():
        for i, rec in enumerate(doc.get("surfaces", [])):
            el, loc, unit = rec.get("elevation"), rec.get("location"), rec.get("unit")
            nav = el.get("navd88") if isinstance(el, dict) else None
            dc = loc.get("derived_coordinates") if isinstance(loc, dict) else None
            if not (nav and dc and isinstance(unit, dict) and _value(rec, "boundary")):
                continue
            lo, hi = nav["value"].get("min_ft"), nav["value"].get("max_ft")
            if lo is None or hi is None:
                continue  # an open bound is not a point elevation
            name = (unit.get("normalized") or {}).get("canonical") or str(unit.get("value"))
            x, y = coords.latlon_to_state_plane(dc["value"]["lat"], dc["value"]["lon"])
            pts.append({"doc": key, "path": f"surfaces[{i}].elevation", "entry": el, "sid": el["source_id"],
                        "unit": name.strip().lower(), "boundary": str(_value(rec, "boundary")).lower(),
                        "measured": _value(rec, "method") == "measured", "x": x, "y": y, "z": (lo + hi) / 2,
                        "approx": bool(nav.get("approximate"))})
    return pts


def apply(docs: dict, cfg: dict = CONFIG) -> tuple[dict, dict]:
    """(copies of docs with agreements recorded, report). The inputs are not modified."""
    out = copy.deepcopy(docs)
    for doc in out.values():
        _reset(doc)
    pts = _points(out)
    links: dict[int, dict] = {}
    report = {"points": len(pts), "agreements": 0, "disagreements": 0, "values_raised": 0}
    for a in range(len(pts)):
        for b in range(a + 1, len(pts)):
            p, q = pts[a], pts[b]
            if p["sid"] == q["sid"] or p["unit"] != q["unit"] or p["boundary"] != q["boundary"]:
                continue
            if not (p["measured"] or q["measured"]):
                continue
            dist = math.hypot(p["x"] - q["x"], p["y"] - q["y"])
            if dist > cfg["distance_ft"]:
                continue
            tol = cfg["unit_tolerance_ft"].get(p["unit"], cfg["tolerance_ft"])
            if p["approx"] or q["approx"]:
                tol += cfg["approximate_extra_ft"]
            agree = abs(p["z"] - q["z"]) <= tol
            report["agreements" if agree else "disagreements"] += 1
            for me, other in ((a, q), (b, p)):
                mine = pts[me]
                rec = links.setdefault(me, {"agrees_with": [], "disagrees_with": [], "tolerance_ft": tol})
                rec["agrees_with" if agree else "disagrees_with"].append({
                    "source_id": other["sid"], "path": other["path"], "page": other["entry"].get("page"),
                    "navd88_ft": round(other["z"], 3), "delta_ft": round(other["z"] - mine["z"], 3),
                    "distance_ft": round(dist, 1), "measured": other["measured"]})
    for idx, rec in links.items():
        el = pts[idx]["entry"]
        k = len({o["source_id"] for o in rec["agrees_with"]})
        nav = el.get("navd88")
        el["agreement"] = {"confidence_before": el["confidence"], "k": k, "formula": FORMULA, "boost": cfg["boost"], "cap": cfg["cap"], **rec}
        el["confidence"] = boosted(el["confidence"], k, cfg)
        if nav and k:
            nav["confidence_before_agreement"] = nav["confidence"]
            nav["confidence"] = boosted(nav["confidence"], k, cfg)
        report["values_raised"] += k > 0
    return out, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record agreement between sources on surface elevations.")
    ap.add_argument("files", nargs="*", type=Path, help="extracted files (default: data/extracted/*.json)")
    ap.add_argument("--write", action="store_true", help="write the files whose agreements changed")
    args = ap.parse_args(argv)
    files = args.files or sorted(ingest.OUT_DIR.glob("*.json"))
    docs = {str(f): json.loads(Path(f).read_text()) for f in files}
    out, report = apply(docs)
    changed = [f for f in docs if out[f] != docs[f]]
    report["files_changed"] = len(changed)
    if args.write:
        for f in changed:
            Path(f).write_text(dumps(out[f]))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
