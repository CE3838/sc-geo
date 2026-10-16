"""Surfaces from point elevations (the top or base of a unit, or a head), with uncertainty.

Pure Python, no numpy. Points are in a plane in feet (SC State Plane; see
`point_from_latlon`), elevations in feet NAVD88 (extract/elevations.py).

`build(points, cfg)` picks the method:

1. Ordinary kriging, the primary method, with at least `min_points_kriging`
   points. An empirical semivariogram (pairs binned to half the largest
   distance) is fitted with spherical, exponential and gaussian models (nugget
   and partial sill by weighted least squares, range by search); the model is
   the one with the lowest leave-one-out RMSE, computed exactly from one
   inverse of the kriging matrix (Dubrule 1983). Each estimate's uncertainty
   is its kriging standard deviation, calibrated by the square root of the
   leave-one-out mean standardized squared error (bounded by `msse_bounds`) so
   it matches the errors cross-validation saw; the raw value is kept as
   `std_raw`.
2. The fallback when there are too few points, when the variogram fit is poor
   (r² below `min_r2`, or almost no spatial structure: partial sill under
   `min_structure` of the sill), or when kriging cross-validates more than
   `cv_margin` worse than the fallback on the same points: natural neighbour (Sibson) inside the
   points' convex hull, inverse distance weighting outside it. Their
   uncertainty is the method's leave-one-out RMSE.

No uncertainty is reported below `min_std_ft` (0.3 ft, the error of
elevations printed to the nearest foot).

No estimate is made farther than `max_distance_ft` from the nearest point
(default `max_distance_factor` times the median nearest-neighbour spacing):
the value is None with a reason. Estimates outside the convex hull are
flagged `extrapolated`. Coincident points are averaged and keep every
reference. Everything returned is an inference (CLAUDE.md rule 2): a caller
that stores an estimate stores it inferred, citing `provenance()`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from model import coords

DEFAULTS = {"min_points_kriging": 10, "min_r2": 0.3, "min_structure": 0.05, "cv_margin": 0.10,
            "idw_power": 2.0, "max_distance_ft": None, "max_distance_factor": 3.0, "bins": 12,
            "msse_bounds": (0.25, 20.0), "min_std_ft": 0.3}
KINDS = ("spherical", "exponential", "gaussian")


@dataclass
class Point:
    x: float
    y: float
    z: float
    ref: object = None
    refs: list = field(default_factory=list)

    def __post_init__(self):
        if not self.refs and self.ref is not None:
            self.refs = [self.ref]


def point_from_latlon(lat: float, lon: float, z: float, ref=None) -> Point:
    """A point in SC State Plane NAD83 international feet."""
    x, y = coords.latlon_to_state_plane(lat, lon, unit="ft")
    return Point(x, y, z, ref)


# --- linear algebra -------------------------------------------------------------

def _lu(a: list[list[float]]):
    n = len(a)
    m = [row[:] for row in a]
    perm = list(range(n))
    scale = max((abs(v) for row in m for v in row), default=1.0) or 1.0
    for k in range(n):
        p = max(range(k, n), key=lambda i: abs(m[i][k]))
        if abs(m[p][k]) <= 1e-13 * scale:
            raise ValueError("singular matrix")
        if p != k:
            m[k], m[p] = m[p], m[k]
            perm[k], perm[p] = perm[p], perm[k]
        piv = m[k][k]
        rk = m[k]
        for i in range(k + 1, n):
            f = m[i][k] / piv
            if f:
                ri = m[i]
                ri[k] = f
                for j in range(k + 1, n):
                    ri[j] -= f * rk[j]
    return m, perm


def _lu_solve(lu, b: list[float]) -> list[float]:
    m, perm = lu
    n = len(m)
    y = [b[perm[i]] for i in range(n)]
    for i in range(n):
        row = m[i]
        y[i] -= sum(row[j] * y[j] for j in range(i))
    for i in range(n - 1, -1, -1):
        row = m[i]
        y[i] = (y[i] - sum(row[j] * y[j] for j in range(i + 1, n))) / row[i]
    return y


def solve(a: list[list[float]], b: list[float]) -> list[float]:
    return _lu_solve(_lu(a), b)


def inverse(a: list[list[float]]) -> list[list[float]]:
    lu = _lu(a)
    n = len(a)
    cols = [_lu_solve(lu, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


# --- variograms ---------------------------------------------------------------------

def _shape(kind: str, h: float, a: float) -> float:
    if kind == "spherical":
        return 1.0 if h >= a else 1.5 * h / a - 0.5 * (h / a) ** 3
    if kind == "exponential":
        return 1.0 - math.exp(-3.0 * h / a)        # practical range a
    if kind == "gaussian":
        return 1.0 - math.exp(-3.0 * (h / a) ** 2)
    raise ValueError(kind)


@dataclass
class Variogram:
    kind: str
    nugget: float
    psill: float
    range: float
    r2: float | None = None

    @property
    def sill(self) -> float:
        return self.nugget + self.psill

    def gamma(self, h: float) -> float:
        return 0.0 if h <= 0 else self.nugget + self.psill * _shape(self.kind, h, self.range)

    def cov(self, h: float) -> float:
        return self.sill if h <= 1e-9 else self.psill * (1.0 - _shape(self.kind, h, self.range))

    def to_dict(self) -> dict:
        return {"kind": self.kind, "nugget": self.nugget, "partial_sill": self.psill, "range_ft": self.range,
                "r2": self.r2}


def empirical_variogram(points: list[Point], nbins: int = DEFAULTS["bins"]) -> list[tuple[float, float, int]]:
    """[(mean lag, semivariance, pairs)] for lags up to half the largest distance; bins with 3+ pairs."""
    pairs = []
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            p, q = points[i], points[j]
            pairs.append((math.hypot(p.x - q.x, p.y - q.y), 0.5 * (p.z - q.z) ** 2))
    if not pairs:
        return []
    maxlag = max(d for d, _ in pairs) / 2
    if maxlag <= 0:
        return []
    width = maxlag / nbins
    acc = [[0.0, 0.0, 0] for _ in range(nbins)]
    for d, g in pairs:
        if 0 < d <= maxlag:
            b = acc[min(int(d / width), nbins - 1)]
            b[0] += d
            b[1] += g
            b[2] += 1
    return [(s / n, g / n, n) for s, g, n in acc if n >= 3]


def _fit_range(bins, kind: str, a: float):
    w = [n for _, _, n in bins]
    f = [_shape(kind, h, a) for h, _, _ in bins]
    g = [gm for _, gm, _ in bins]
    sw = sum(w)
    swf = sum(wi * fi for wi, fi in zip(w, f))
    swff = sum(wi * fi * fi for wi, fi in zip(w, f))
    swg = sum(wi * gi for wi, gi in zip(w, g))
    swfg = sum(wi * fi * gi for wi, fi, gi in zip(w, f, g))
    det = sw * swff - swf * swf
    c0, c = ((swff * swg - swf * swfg) / det, (sw * swfg - swf * swg) / det) if abs(det) > 1e-12 else (-1.0, 0.0)
    if c0 < 0:
        c0, c = 0.0, (swfg / swff if swff > 0 else 0.0)
    if c < 0:
        c0, c = swg / sw, 0.0
    sse = sum(wi * (gi - c0 - c * fi) ** 2 for wi, fi, gi in zip(w, f, g))
    return sse, c0, c


def fit_variogram(bins, kind: str) -> Variogram | None:
    """Weighted least-squares fit (weights = pairs per bin); range by a coarse then a fine search."""
    if len(bins) < 3:
        return None
    lo, hi = bins[0][0] * 0.5, bins[-1][0] * 3.0
    cands = [lo * (hi / lo) ** (i / 59) for i in range(60)]
    best = min(((*_fit_range(bins, kind, a), a) for a in cands), key=lambda t: t[0])
    a0 = best[3]
    fine = [a0 * (0.8 + 0.4 * i / 80) for i in range(81)]
    sse, c0, c, a = min(((*_fit_range(bins, kind, a), a) for a in fine + [a0]), key=lambda t: t[0])
    w = [n for _, _, n in bins]
    mean = sum(wi * g for wi, (_, g, _) in zip(w, bins)) / sum(w)
    sst = sum(wi * (g - mean) ** 2 for wi, (_, g, _) in zip(w, bins))
    r2 = 1 - sse / sst if sst > 0 else 0.0
    return Variogram(kind, c0, c, a, r2)


# --- estimators -------------------------------------------------------------------------

class Kriging:
    """Ordinary kriging in covariance form, one matrix inverse reused for every estimate."""

    def __init__(self, points: list[Point], vg: Variogram):
        self.points, self.vg = points, vg
        n = len(points)
        jitter = 1e-10 * (vg.sill or 1.0)
        k = [[0.0] * (n + 1) for _ in range(n + 1)]
        for i, p in enumerate(points):
            for j in range(i, n):
                q = points[j]
                c = vg.cov(math.hypot(p.x - q.x, p.y - q.y)) + (jitter if i == j else 0.0)
                k[i][j] = k[j][i] = c
            k[i][n] = k[n][i] = 1.0
        self.kinv = inverse(k)

    def predict(self, x: float, y: float) -> tuple[float, float]:
        """(estimate, kriging variance)."""
        n = len(self.points)
        rhs = [self.vg.cov(math.hypot(p.x - x, p.y - y)) for p in self.points] + [1.0]
        sol = [sum(r[j] * rhs[j] for j in range(n + 1)) for r in self.kinv]
        est = sum(sol[i] * self.points[i].z for i in range(n))
        var = self.vg.sill - sum(sol[i] * rhs[i] for i in range(n)) - sol[n]
        return est, max(var, 0.0)

    def leave_one_out(self) -> tuple[list[float], list[float]]:
        """(z_i minus the estimate without point i, its kriging variance), for every i, exactly."""
        n = len(self.points)
        b = [p.z for p in self.points] + [0.0]
        alpha = [sum(r[j] * b[j] for j in range(n + 1)) for r in self.kinv]
        return ([alpha[i] / self.kinv[i][i] for i in range(n)], [1.0 / self.kinv[i][i] for i in range(n)])


class IDW:
    def __init__(self, points: list[Point], power: float = 2.0):
        self.points, self.power = points, power

    def predict(self, x: float, y: float, skip: int | None = None) -> float | None:
        num = den = 0.0
        for i, p in enumerate(self.points):
            if i == skip:
                continue
            d = math.hypot(p.x - x, p.y - y)
            if d < 1e-9:
                return p.z
            w = d ** -self.power
            num += w * p.z
            den += w
        return num / den if den else None


def _circum(ax, ay, bx, by, cx, cy):
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2


def _hull(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _area(poly) -> float:
    return abs(sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly)))) / 2


def _inside(hull, x, y, tol=1e-9) -> bool:
    if len(hull) < 3:
        return False
    for i in range(len(hull)):
        (ax, ay), (bx, by) = hull[i - 1], hull[i]
        if (bx - ax) * (y - ay) - (by - ay) * (x - ax) < -tol * max(1.0, math.hypot(bx - ax, by - ay)):
            return False
    return True


class NaturalNeighbor:
    """Sibson natural-neighbour interpolation on a Bowyer-Watson Delaunay triangulation.

    Inside the convex hull only (None outside); reproduces linear surfaces exactly."""

    def __init__(self, points: list[Point]):
        self.points = points
        xs, ys = [p.x for p in points], [p.y for p in points]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        big = span * 1e4
        self.v = [(p.x, p.y) for p in points] + [(mx - 2 * big, my - big), (mx + 2 * big, my - big), (mx, my + 2 * big)]
        n = len(points)
        self.super = {n, n + 1, n + 2}
        self.tris = [self._tri(n, n + 1, n + 2)]
        for i in range(n):
            self._insert(i)
        self.hull = _hull([(p.x, p.y) for p in points])

    def _tri(self, a, b, c):
        cc = _circum(*self.v[a], *self.v[b], *self.v[c])
        return (a, b, c, cc)

    def _bad(self, x, y):
        out = []
        for t in self.tris:
            cc = t[3]
            if cc and (x - cc[0]) ** 2 + (y - cc[1]) ** 2 < cc[2] * (1 - 1e-12):
                out.append(t)
        return out

    @staticmethod
    def _boundary(bad):
        count: dict = {}
        for a, b, c, _ in bad:
            for e in ((a, b), (b, c), (c, a)):
                k = tuple(sorted(e))
                count[k] = count.get(k, 0) + 1
        return [e for e, n in count.items() if n == 1]

    def _insert(self, i):
        x, y = self.v[i]
        bad = self._bad(x, y)
        edges = self._boundary(bad)
        bad_ids = {id(t) for t in bad}
        self.tris = [t for t in self.tris if id(t) not in bad_ids]
        for a, b in edges:
            t = self._tri(a, b, i)
            if t[3] is not None:
                self.tris.append(t)

    def predict(self, x: float, y: float) -> float | None:
        for p in self.points:
            if abs(p.x - x) < 1e-9 and abs(p.y - y) < 1e-9:
                return p.z
        if not _inside(self.hull, x, y):
            return None
        bad = self._bad(x, y)
        if not bad or any(set(t[:3]) & self.super for t in bad):
            return None
        edges = self._boundary(bad)
        new_cc = {}
        for a, b in edges:
            cc = _circum(x, y, *self.v[a], *self.v[b])
            if cc is None:
                return None
            new_cc[(a, b)] = cc[:2]
        areas = {}
        for p in {v for e in edges for v in e}:
            poly = [cc for e, cc in new_cc.items() if p in e] + [t[3][:2] for t in bad if p in t[:3]]
            areas[p] = _area(_hull(poly))
        total = sum(areas.values())
        if total <= 0:
            return None
        return sum(areas[p] * self.points[p].z for p in areas) / total


# --- building a surface ------------------------------------------------------------------

def _merge(points: list[Point]) -> list[Point]:
    groups: dict = {}
    for p in points:
        groups.setdefault((round(p.x, 2), round(p.y, 2)), []).append(p)
    out = []
    for g in groups.values():
        refs = [r for p in g for r in p.refs]
        out.append(Point(g[0].x, g[0].y, sum(p.z for p in g) / len(g), refs=refs))
    return out


def _stats(errs: list[float], variances: list[float] | None = None) -> dict:
    n = len(errs)
    out = {"n": n, "rmse": math.sqrt(sum(e * e for e in errs) / n) if n else None,
           "mae": sum(abs(e) for e in errs) / n if n else None}
    if variances is not None and n:
        ok = [(e, v) for e, v in zip(errs, variances) if v > 0]
        out["msse"] = sum(e * e / v for e, v in ok) / len(ok) if ok else None
    return out


class Surface:
    def __init__(self, points, cfg, method, reason, variogram=None, kriging=None, cv=None, cv_models=None):
        self.points, self.cfg, self.method, self.reason = points, cfg, method, reason
        self.variogram, self.kriging = variogram, kriging
        self.cv, self.cv_models = cv or {}, cv_models or {}
        self.idw = IDW(points, cfg["idw_power"])
        self.nn = NaturalNeighbor(points) if len(points) >= 3 and method == "natural_neighbor" else None
        self.hull = _hull([(p.x, p.y) for p in points])
        # Kriging variances scale with the fitted sill, which a trend or a few pairs can inflate or
        # shrink; the leave-one-out mean standardized squared error (ideally 1) rescales them.
        msse = (self.cv.get("kriging") or {}).get("msse")
        lo, hi = cfg["msse_bounds"]
        self.std_factor = math.sqrt(min(max(msse, lo), hi)) if msse else 1.0
        self.max_distance_ft = cfg["max_distance_ft"]
        if self.max_distance_ft is None:
            nn = [min(math.hypot(p.x - q.x, p.y - q.y) for q in points if q is not p) for p in points] \
                if len(points) > 1 else []
            self.max_distance_ft = cfg["max_distance_factor"] * sorted(nn)[len(nn) // 2] if nn else 0.0

    def estimate(self, x: float, y: float) -> dict:
        nearest = min(math.hypot(p.x - x, p.y - y) for p in self.points)
        inside = _inside(self.hull, x, y)
        base = {"nearest_ft": nearest, "inside_hull": inside, "extrapolated": not inside,
                "n_points": len(self.points), "max_distance_ft": self.max_distance_ft}
        if nearest > self.max_distance_ft + 1e-9:
            return {"value": None, "std": None, "std_kind": None, "method": None,
                    "reason": f"beyond {self.max_distance_ft:.0f} ft from the nearest point", **base}
        if self.method == "kriging":
            est, var = self.kriging.predict(x, y)
            raw = math.sqrt(var)
            return {"value": est, "std": max(raw * self.std_factor, self.cfg["min_std_ft"]), "std_raw": raw,
                    "std_kind": "kriging standard deviation (calibrated by cross-validation)",
                    "method": "kriging", "reason": None, **base}
        method, value = "idw", None
        if self.nn is not None and inside:
            value = self.nn.predict(x, y)
            method = "natural_neighbor" if value is not None else "idw"
        if value is None:
            value = self.idw.predict(x, y)
        cv = self.cv.get(method)
        std = max(cv["rmse"], self.cfg["min_std_ft"]) if cv and cv["n"] else None
        return {"value": value, "std": std, "std_kind": "leave-one-out RMSE" if std is not None else None,
                "method": method, "reason": None if std is not None else "no cross-validation with one point",
                **base}

    def provenance(self) -> dict:
        return {"method": self.method, "reason": self.reason, "inferred": True, "extraction_method": "inference",
                "variogram": self.variogram.to_dict() if self.variogram else None, "cv": self.cv,
                "std_factor": self.std_factor,
                "cv_models": self.cv_models, "max_distance_ft": self.max_distance_ft,
                "points": [{"x": p.x, "y": p.y, "z": p.z, "refs": p.refs} for p in self.points]}


def build(points: list[Point], cfg: dict | None = None) -> Surface:
    cfg = {**DEFAULTS, **(cfg or {})}
    pts = _merge(points)
    n = len(pts)
    if n == 0:
        raise ValueError("no points")
    cv: dict = {}
    idw_err: list[float] = []
    nn_err: list[float | None] = [None] * n
    if n >= 2:
        idw = IDW(pts, cfg["idw_power"])
        idw_err = [p.z - idw.predict(p.x, p.y, skip=i) for i, p in enumerate(pts)]
        cv["idw"] = _stats(idw_err)
    if n >= 4:
        for i, p in enumerate(pts):
            est = NaturalNeighbor(pts[:i] + pts[i + 1:]).predict(p.x, p.y)
            nn_err[i] = None if est is None else p.z - est
        cv["natural_neighbor"] = _stats([e for e in nn_err if e is not None])
    if idw_err:
        # What the fallback would do at every point: natural neighbour inside the hull, IDW elsewhere.
        cv["fallback"] = _stats([nn if nn is not None else iw for nn, iw in zip(nn_err, idw_err)])
    fallback = "natural_neighbor" if n >= 3 else "idw"
    if n < cfg["min_points_kriging"]:
        return Surface(pts, cfg, fallback, f"fewer than {cfg['min_points_kriging']} points for a variogram", cv=cv)
    bins = empirical_variogram(pts, cfg["bins"])
    cv_models, fits = {}, {}
    for kind in KINDS:
        vg = fit_variogram(bins, kind)
        if vg is None or vg.psill <= 0:
            continue
        try:
            k = Kriging(pts, vg)
        except ValueError:
            continue
        errs, variances = k.leave_one_out()
        cv_models[kind] = _stats(errs, variances) | {"variogram": vg.to_dict()}
        fits[kind] = (vg, k)
    if not fits:
        return Surface(pts, cfg, fallback, "no variogram model could be fitted", cv=cv)
    kind = min(cv_models, key=lambda k: cv_models[k]["rmse"])
    vg, krig = fits[kind]
    cv["kriging"] = {k: v for k, v in cv_models[kind].items() if k != "variogram"}
    if vg.r2 < cfg["min_r2"]:
        reason = f"poor variogram fit (r2 {vg.r2:.2f} < {cfg['min_r2']})"
    elif vg.psill < cfg["min_structure"] * vg.sill:
        reason = "no spatial structure in the variogram (almost all nugget)"
    else:
        other = cv.get("fallback", {}).get("rmse")
        if other is not None and cv["kriging"]["rmse"] > (1 + cfg["cv_margin"]) * other:
            reason = "kriging with the fitted variogram cross-validates worse than the fallback"
        else:
            return Surface(pts, cfg, "kriging", f"{kind} variogram chosen by leave-one-out cross-validation",
                           vg, krig, cv, cv_models)
    return Surface(pts, cfg, fallback, reason, vg, None, cv, cv_models)
