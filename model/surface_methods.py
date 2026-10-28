"""Experimental interpolators for subsurface surfaces, measured against model/surfaces.build().

Research code for docs/interpolation.md. Nothing here is used by build() or
changes its defaults; a method moves into model/surfaces.py only after the
user approves it.

* `UniversalKriging`: kriging with a polynomial drift (constant = ordinary
  kriging, linear = a planar regional dip, quadratic), in covariance form.
  The variogram is fitted to the ordinary-least-squares residuals of the same
  drift (regression kriging; Hengl and others, 2007). Leave-one-out errors
  come exactly from one inverse of the kriging matrix, as in
  model/surfaces.py (Dubrule, 1983, covers the drift case).
* `fit_anisotropy`: geometric anisotropy by a grid search over the azimuth of
  the long axis and the range ratio, scored by leave-one-out RMSE. The
  choice is made on the same errors it reports, so its RMSE is slightly
  optimistic (docs/interpolation.md says so next to the numbers).
* `contact_points`: surface points from logged holes already in
  data/extracted: the top of a unit buried under a different unit is the
  hole's NAVD88 land-surface elevation minus the logged depth to that unit.
  Every point is an inference and its references say so.

    python -m model.surface_methods [--min-points 10] [--json OUT.json]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from model import coords, surfaces
from model.surfaces import KINDS, Point, Variogram, empirical_variogram, fit_variogram, inverse

ROOT = Path(__file__).resolve().parent.parent
DRIFTS = ("constant", "linear", "quadratic")
AZIMUTHS = tuple(range(0, 180, 15))
RATIOS = (1.0, 1.5, 2.0, 3.0, 4.0)


# --- drift ---------------------------------------------------------------------

class _Frame:
    """Centred, scaled coordinates so polynomial drift terms stay well conditioned."""

    def __init__(self, points: list[Point]):
        xs, ys = [p.x for p in points], [p.y for p in points]
        self.mx, self.my = sum(xs) / len(xs), sum(ys) / len(ys)
        self.s = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)

    def terms(self, drift: str, x: float, y: float) -> list[float]:
        u, v = (x - self.mx) / self.s, (y - self.my) / self.s
        if drift == "constant":
            return [1.0]
        if drift == "linear":
            return [1.0, u, v]
        if drift == "quadratic":
            return [1.0, u, v, u * u, u * v, v * v]
        raise ValueError(drift)


def fit_trend(points: list[Point], drift: str = "linear"):
    """Ordinary least-squares polynomial trend; returns f(x, y)."""
    frame = _Frame(points)
    rows = [frame.terms(drift, p.x, p.y) for p in points]
    m = len(rows[0])
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(m)] for i in range(m)]
    atb = [sum(r[i] * p.z for r, p in zip(rows, points)) for i in range(m)]
    beta = surfaces.solve(ata, atb)
    return lambda x, y: sum(b * t for b, t in zip(beta, frame.terms(drift, x, y)))


def residuals(points: list[Point], trend) -> list[Point]:
    return [Point(p.x, p.y, p.z - trend(p.x, p.y), refs=p.refs) for p in points]


class UniversalKriging:
    """Kriging with a polynomial drift: [[C, F], [F^T, 0]] [w; mu] = [c; f]."""

    def __init__(self, points: list[Point], vg: Variogram, drift: str = "linear"):
        self.points, self.vg, self.drift = points, vg, drift
        self.frame = _Frame(points)
        n = len(points)
        f = [self.frame.terms(drift, p.x, p.y) for p in points]
        m = len(f[0])
        jitter = 1e-10 * (vg.sill or 1.0)
        k = [[0.0] * (n + m) for _ in range(n + m)]
        for i, p in enumerate(points):
            for j in range(i, n):
                q = points[j]
                c = vg.cov(math.hypot(p.x - q.x, p.y - q.y)) + (jitter if i == j else 0.0)
                k[i][j] = k[j][i] = c
            for t in range(m):
                k[i][n + t] = k[n + t][i] = f[i][t]
        self.m = m
        self.kinv = inverse(k)

    def predict(self, x: float, y: float) -> tuple[float, float]:
        """(estimate, kriging variance)."""
        n = len(self.points)
        c = [self.vg.cov(math.hypot(p.x - x, p.y - y)) for p in self.points]
        rhs = c + self.frame.terms(self.drift, x, y)
        sol = [sum(r[j] * rhs[j] for j in range(n + self.m)) for r in self.kinv]
        est = sum(sol[i] * self.points[i].z for i in range(n))
        var = self.vg.sill - sum(sol[i] * rhs[i] for i in range(n + self.m))
        return est, max(var, 0.0)

    def leave_one_out(self) -> tuple[list[float], list[float]]:
        n = len(self.points)
        b = [p.z for p in self.points] + [0.0] * self.m
        alpha = [sum(r[j] * b[j] for j in range(n + self.m)) for r in self.kinv]
        return [alpha[i] / self.kinv[i][i] for i in range(n)], [1.0 / self.kinv[i][i] for i in range(n)]


# --- scoring -------------------------------------------------------------------

def stats(errs: list[float], variances: list[float] | None = None) -> dict:
    """Errors are observed minus estimated, as in model/surfaces.py."""
    n = len(errs)
    out = {"n": n, "rmse": math.sqrt(sum(e * e for e in errs) / n) if n else None,
           "mae": sum(abs(e) for e in errs) / n if n else None, "bias": sum(errs) / n if n else None, "msse": None}
    if variances:
        ok = [(e, v) for e, v in zip(errs, variances) if v > 0]
        out["msse"] = sum(e * e / v for e, v in ok) / len(ok) if ok else None
    return out


def kriging_cv(points: list[Point], drift: str = "constant", kinds=KINDS, bins: int = surfaces.DEFAULTS["bins"]):
    """Best variogram kind by leave-one-out RMSE: (stats, Variogram) or (None, None)."""
    base = residuals(points, fit_trend(points, drift)) if drift != "constant" else points
    emp = empirical_variogram(base, bins)
    best = (None, None)
    for kind in kinds:
        vg = fit_variogram(emp, kind)
        if vg is None or vg.psill <= 0:
            continue
        try:
            errs, var = UniversalKriging(points, vg, drift).leave_one_out()
        except ValueError:
            continue
        st = stats(errs, var)
        if best[0] is None or st["rmse"] < best[0]["rmse"]:
            best = (st, vg)
    return best


def transform(points: list[Point], azimuth_deg: float, ratio: float) -> list[Point]:
    """Coordinates in which an anisotropic variogram is isotropic.

    `azimuth_deg` is the long axis (greatest continuity), clockwise from north;
    distances along it are divided by `ratio`."""
    a = math.radians(azimuth_deg)
    ux, uy = math.sin(a), math.cos(a)
    return [Point(((p.x * ux + p.y * uy) / ratio), (p.x * uy - p.y * ux), p.z, refs=p.refs) for p in points]


def fit_anisotropy(points: list[Point], drift: str = "constant", azimuths=AZIMUTHS, ratios=RATIOS, kinds=None) -> dict:
    """Grid search over (azimuth, ratio, variogram kind) by leave-one-out RMSE."""
    if kinds is None:
        st, vg = kriging_cv(points, drift)
        kinds = (vg.kind,) if vg else KINDS
    best = None
    for ratio in ratios:
        for az in (azimuths if ratio != 1.0 else (0,)):
            st, vg = kriging_cv(transform(points, az, ratio), drift, kinds)
            if st and (best is None or st["rmse"] < best["cv"]["rmse"]):
                best = {"azimuth_deg": float(az), "ratio": ratio, "variogram": vg.to_dict(), "cv": st}
    return best or {"azimuth_deg": None, "ratio": None, "variogram": None, "cv": None}


def nested_anisotropy_errors(points: list[Point], drift: str = "constant", azimuths=AZIMUTHS,
                             ratios=RATIOS) -> list[float]:
    """Honest leave-one-out errors for the anisotropy search: for each point the
    azimuth, ratio and variogram are chosen on the other points only."""
    errs = []
    for i, p in enumerate(points):
        rest = points[:i] + points[i + 1:]
        fit = fit_anisotropy(rest, drift, azimuths, ratios)
        if fit["variogram"] is None:
            errs.append(float("nan"))
            continue
        v = fit["variogram"]
        vg = Variogram(v["kind"], v["nugget"], v["partial_sill"], v["range_ft"], v["r2"])
        t_rest = transform(rest, fit["azimuth_deg"], fit["ratio"])
        (tp,) = transform([p], fit["azimuth_deg"], fit["ratio"])
        est, _ = UniversalKriging(t_rest, vg, drift).predict(tp.x, tp.y)
        errs.append(p.z - est)
    return [e for e in errs if e == e]


def fallback_errors(points: list[Point], power: float = surfaces.DEFAULTS["idw_power"]) -> list[float]:
    """What build()'s fallback does at each point: natural neighbour inside the hull, else IDW."""
    idw = surfaces.IDW(points, power)
    out = []
    for i, p in enumerate(points):
        est = surfaces.NaturalNeighbor(points[:i] + points[i + 1:]).predict(p.x, p.y) if len(points) >= 4 else None
        out.append(p.z - (est if est is not None else idw.predict(p.x, p.y, skip=i)))
    return out


METHODS = ("current", "fallback", "ok", "uk_linear", "uk_quadratic", "ok_aniso", "uk_linear_aniso")
NESTED = ("ok_aniso_nested", "uk_linear_aniso_nested")


def compare(points: list[Point], methods=METHODS) -> list[dict]:
    """One row per method: leave-one-out n, RMSE, MAE, bias (mean observed minus estimate), MSSE."""
    pts = surfaces._merge(points)
    rows = []
    for m in methods:
        detail = ""
        if m == "current":
            s = surfaces.build(pts)
            if s.method == "kriging":
                st = stats(*s.kriging.leave_one_out())
            else:
                st = stats(fallback_errors(pts, s.cfg["idw_power"]))
            detail = f"{s.method}: {s.reason}"
        elif m == "fallback":
            st, detail = stats(fallback_errors(pts)), "natural neighbour, IDW outside the hull"
        elif m in ("ok", "uk_linear", "uk_quadratic"):
            drift = {"ok": "constant", "uk_linear": "linear", "uk_quadratic": "quadratic"}[m]
            if drift == "quadratic" and len(pts) < 20:
                continue
            st, vg = kriging_cv(pts, drift)
            if st is None:
                continue
            detail = f"{drift} drift, {vg.kind} variogram (range {vg.range:.0f} ft)"
        elif m.endswith("_nested"):
            drift = "constant" if m.startswith("ok_") else "linear"
            st = stats(nested_anisotropy_errors(pts, drift))
            detail = f"{drift} drift, anisotropy chosen without the held-out point (nested)"
        else:
            drift = "constant" if m == "ok_aniso" else "linear"
            fit = fit_anisotropy(pts, drift)
            if fit["cv"] is None:
                continue
            st = fit["cv"]
            detail = (f"{drift} drift, {fit['variogram']['kind']}, long axis N{fit['azimuth_deg']:.0f}E, "
                      f"ratio {fit['ratio']:g} (chosen on these errors)")
        rows.append({"method": m, **st, "detail": detail})
    return rows


# --- points from data/extracted ------------------------------------------------

_ELEVATION_TEXT = re.compile(r"sea level|\bmsl\b|elevation|altitude|ngvd|navd|datum", re.I)


def _value(node, key="value"):
    return node.get(key) if isinstance(node, dict) else None


def contact_points(docs: dict) -> dict[tuple[str, str], list[Point]]:
    """{(unit, "top"): points, ("land surface", source_id): points} from logged holes.

    A hole counts when it has derived coordinates and a single NAVD88 land-surface
    elevation; intervals must be depths below land surface (an interval printed
    as an elevation or against a datum is skipped). Only tops of units buried
    under a different unit are taken: a unit at the land surface has no top
    contact in that hole."""
    out: dict[tuple[str, str], list[Point]] = {}
    for key, doc in docs.items():
        for i, rec in enumerate(doc.get("observations", []) or []):
            dc = _value(rec.get("location"), "derived_coordinates")
            nav = _value(rec.get("elevation"), "navd88")
            if not (dc and nav):
                continue
            lo, hi = nav["value"].get("min_ft"), nav["value"].get("max_ft")
            if lo is None or hi is None or abs(hi - lo) > 1e-9:
                continue
            ref_kind = str(_value(rec.get("depth_reference")) or "land surface").lower()
            x, y = coords.latlon_to_state_plane(dc["value"]["lat"], dc["value"]["lon"])
            land_ref = {"source_id": nav["source_id"], "page": nav.get("page"), "doc": key,
                        "path": f"observations[{i}].elevation.navd88", "extraction_method": "datum_conversion",
                        "confidence": nav.get("confidence"), "inferred": True}
            out.setdefault(("land surface", nav["source_id"]), []).append(Point(x, y, lo, ref=land_ref))
            if ref_kind != "land surface":
                continue
            seq = []
            for j, iv in enumerate(rec.get("intervals", []) or []):
                top, unit = iv.get("top"), iv.get("unit")
                norm = _value(top, "normalized")
                if not (isinstance(unit, dict) and norm and norm.get("min_ft") is not None):
                    continue
                if _ELEVATION_TEXT.search(f"{top.get('value')} {top.get('units') or ''}"):
                    continue
                name = ((unit.get("normalized") or {}).get("canonical") or str(unit.get("value"))).strip().lower()
                seq.append((norm["min_ft"], name, j, top))
            seq.sort(key=lambda t: t[0])
            seen = set()
            prev = None
            for depth, name, j, top in seq:
                if name != prev and prev is not None and name not in seen and depth > 0:
                    conf = min(c for c in (nav.get("confidence"), top.get("confidence"), dc.get("confidence"))
                               if c is not None)
                    ref = {"source_id": top["source_id"], "page": top.get("page"), "doc": key,
                           "path": f"observations[{i}].intervals[{j}].top",
                           "elevation_path": f"observations[{i}].elevation.navd88",
                           "extraction_method": "inference", "confidence": round(conf, 3), "inferred": True,
                           "note": "NAVD88 land-surface elevation minus the logged depth to the unit"}
                    out.setdefault((name, "top"), []).append(Point(x, y, lo - depth, ref=ref))
                seen.add(name)
                prev = name
    return out


def unit_order(docs: dict) -> dict[tuple[str, str], int]:
    """How many holes log unit a above unit b (first appearance), for stacking checks."""
    order: dict[tuple[str, str], int] = {}
    for doc in docs.values():
        for rec in doc.get("observations", []) or []:
            seq = []
            for iv in rec.get("intervals", []) or []:
                norm, unit = _value(iv.get("top"), "normalized"), iv.get("unit")
                if norm and isinstance(unit, dict) and norm.get("min_ft") is not None:
                    name = ((unit.get("normalized") or {}).get("canonical") or str(unit.get("value"))).strip().lower()
                    seq.append((norm["min_ft"], name))
            first = []
            for _, name in sorted(seq):
                if name not in first:
                    first.append(name)
            for a in range(len(first)):
                for b in range(a + 1, len(first)):
                    order[(first[a], first[b])] = order.get((first[a], first[b]), 0) + 1
    return order


def crossings(upper: surfaces.Surface, lower: surfaces.Surface, step_ft: float = 2000.0) -> dict:
    """Grid nodes where both surfaces have an estimate and the lower one comes out above the upper."""
    xs = [p.x for p in upper.points + lower.points]
    ys = [p.y for p in upper.points + lower.points]
    nodes = crossed = 0
    worst = 0.0
    x = min(xs)
    while x <= max(xs):
        y = min(ys)
        while y <= max(ys):
            a, b = upper.estimate(x, y), lower.estimate(x, y)
            if a["value"] is not None and b["value"] is not None:
                nodes += 1
                if b["value"] > a["value"]:
                    crossed += 1
                    worst = max(worst, b["value"] - a["value"])
            y += step_ft
        x += step_ft
    return {"nodes": nodes, "crossed": crossed, "worst_ft": round(worst, 2)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare interpolators by leave-one-out cross-validation.")
    ap.add_argument("--min-points", type=int, default=surfaces.DEFAULTS["min_points_kriging"])
    ap.add_argument("--max-points", type=int, default=150, help="skip larger sets (pure Python, O(n^3))")
    ap.add_argument("--nested-max", type=int, default=60, help="nested anisotropy CV up to this many points")
    ap.add_argument("--json", type=Path, help="write the results here")
    args = ap.parse_args(argv)
    docs = {str(f.relative_to(ROOT)): json.loads(f.read_text()) for f in sorted((ROOT / "data" / "extracted").glob("*.json"))}
    sets = contact_points(docs)
    results, seen = [], set()
    for (unit, boundary), pts in sorted(sets.items(), key=lambda kv: -len(kv[1])):
        n = len(surfaces._merge(pts))
        sig = tuple(sorted((round(p.x), round(p.y), round(p.z, 2)) for p in pts))
        if not args.min_points <= n <= args.max_points or sig in seen:
            continue  # the same points under another record are measured once
        seen.add(sig)
        srcs = sorted({r["source_id"] for p in pts for r in p.refs})
        rows = compare(pts, METHODS + (NESTED if n <= args.nested_max else ()))
        results.append({"surface": f"{boundary} of {unit}" if boundary == "top" else f"{unit} ({boundary})",
                        "sources": srcs, "n": n, "rows": rows})
        print(f"\n{results[-1]['surface']}  n={n}  sources={', '.join(srcs)}")
        for r in rows:
            msse = f"{r['msse']:.2f}" if r["msse"] is not None else "-"
            print(f"  {r['method']:<16} rmse {r['rmse']:7.2f}  mae {r['mae']:7.2f}  bias {r['bias']:+6.2f}  "
                  f"msse {msse:>5}  {r['detail']}")
    # Stacking: do the current surfaces of units logged one above the other cross?
    order = unit_order(docs)
    tops = {u: surfaces.build(p) for (u, b), p in sets.items()
            if b == "top" and len(surfaces._merge(p)) >= args.min_points}
    stack = []
    for (a, b), k in sorted(order.items(), key=lambda kv: -kv[1]):
        if a in tops and b in tops and k >= 3 and order.get((b, a), 0) == 0:
            stack.append({"upper": a, "lower": b, "holes": k, **crossings(tops[a], tops[b])})
            print(f"stack {a} over {b} ({k} holes): {stack[-1]}")
    if args.json:
        args.json.write_text(json.dumps({"surfaces": results, "stacking": stack}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
