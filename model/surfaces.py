"""Surfaces from point elevations (the top or base of a unit, or a head), with uncertainty.

Pure Python, no numpy. Points are in a plane in feet (SC State Plane; see
`point_from_latlon`), elevations in feet NAVD88 (extract/elevations.py).

`build(points, cfg)` tries up to three candidates on the same points and keeps
the one with the lowest leave-one-out (LOO) RMSE:

1. Ordinary kriging (`kriging`), with at least `min_points_kriging` points. An
   empirical semivariogram (pairs binned to half the largest distance) is
   fitted with spherical, exponential and gaussian models (nugget and partial
   sill by weighted least squares, range by search); the model kept is the one
   with the lowest LOO RMSE, computed exactly from one inverse of the kriging
   matrix (Dubrule 1983).
2. Trend kriging (`trend_kriging`, universal kriging with a planar drift),
   with the same minimum: the regional dip is carried by the drift and the
   variogram, fitted to the residuals of a least-squares plane (regression
   kriging; Hengl and others 2007), carries only the local structure. The
   fitted dip (ft per mile and its azimuth, from the kriging's own
   generalized least-squares drift) is reported in `provenance()["trend"]`.
   A quadratic drift is not a candidate: on the extracted tops it won as
   often as it lost (docs/interpolation.md).
3. The fallback: natural neighbour (Sibson) inside the points' convex hull,
   inverse distance weighting outside it.

The kriging candidate with the lower LOO RMSE is kept unless it cross-validates
more than `cv_margin` worse than the fallback (the margin favours kriging, whose
uncertainty varies with distance to the data). There is no variogram-fit gate:
a noisy empirical variogram with a low r² can still krige well, and LOO is the
judge. Fewer than `min_points_kriging` points, or no variogram model with a
positive partial sill, leaves the fallback.

Each kriging estimate's uncertainty is its kriging standard deviation,
calibrated by the square root of the method's LOO mean standardized squared
error (bounded by `msse_bounds`) so it matches the errors cross-validation saw;
the raw value is kept as `std_raw`. The fallback's uncertainty is its LOO RMSE.

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

DEFAULTS = {"min_points_kriging": 10, "cv_margin": 0.10,
            "idw_power": 2.0, "max_distance_ft": None, "max_distance_factor": 3.0, "bins": 12,
            "msse_bounds": (0.25, 20.0), "min_std_ft": 0.3}
KINDS = ("spherical", "exponential", "gaussian")
KRIGING_METHODS = ("kriging", "trend_kriging")
LABELS = {"kriging": "ordinary kriging", "trend_kriging": "trend kriging (planar regional dip)",
          "natural_neighbor": "natural neighbour", "idw": "inverse distance weighting"}
FT_PER_MILE = 5280.0


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
    beta = solve(ata, atb)
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

    def drift_coefficients(self) -> list[float]:
        """The generalized least-squares drift the kriging uses (the drift rows of the inverse times z)."""
        n = len(self.points)
        return [sum(self.kinv[n + t][i] * self.points[i].z for i in range(n)) for t in range(self.m)]

    def gradient(self) -> tuple[float, float]:
        """dz/dx, dz/dy of a linear drift, in feet per foot."""
        if self.drift != "linear":
            raise ValueError("gradient of a linear drift only")
        _, bu, bv = self.drift_coefficients()
        return bu / self.frame.s, bv / self.frame.s


def bearing(azimuth_deg: float) -> str:
    """Quadrant bearing ('S28°E') for an azimuth clockwise from north."""
    a = azimuth_deg % 360.0
    if a <= 90:
        return f"N{a:.0f}°E"
    if a <= 180:
        return f"S{180 - a:.0f}°E"
    if a <= 270:
        return f"S{a - 180:.0f}°W"
    return f"N{360 - a:.0f}°W"


def dip(gx: float, gy: float) -> dict:
    """Dip of a plane with gradient (gx, gy) ft/ft: magnitude in ft per mile and the down-dip azimuth."""
    az = math.degrees(math.atan2(-gx, -gy)) % 360.0
    return {"dip_ft_per_mile": math.hypot(gx, gy) * FT_PER_MILE, "dip_azimuth_deg": az, "dip_direction": bearing(az)}


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
           "mae": sum(abs(e) for e in errs) / n if n else None, "bias": sum(errs) / n if n else None}
    if variances is not None and n:
        ok = [(e, v) for e, v in zip(errs, variances) if v > 0]
        out["msse"] = sum(e * e / v for e, v in ok) / len(ok) if ok else None
    return out


class Surface:
    def __init__(self, points, cfg, method, reason, variogram=None, kriging=None, cv=None, cv_models=None,
                 trend=None, candidates=None):
        self.points, self.cfg, self.method, self.reason = points, cfg, method, reason
        self.variogram, self.kriging = variogram, kriging
        self.cv, self.cv_models = cv or {}, cv_models or {}
        self.trend, self.candidates = trend, candidates or {}
        self.idw = IDW(points, cfg["idw_power"])
        self.nn = NaturalNeighbor(points) if len(points) >= 3 and method == "natural_neighbor" else None
        self.hull = _hull([(p.x, p.y) for p in points])
        # Kriging variances scale with the fitted sill, which a trend or a few pairs can inflate or
        # shrink; the leave-one-out mean standardized squared error (ideally 1) rescales them.
        msse = (self.cv.get(method) or {}).get("msse") if method in KRIGING_METHODS else None
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
        if self.method in KRIGING_METHODS:
            est, var = self.kriging.predict(x, y)
            raw = math.sqrt(var)
            return {"value": est, "std": max(raw * self.std_factor, self.cfg["min_std_ft"]), "std_raw": raw,
                    "std_kind": "kriging standard deviation (calibrated by cross-validation)",
                    "method": self.method, "reason": None, **base}
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
                "selection": (f"lowest leave-one-out RMSE among kriging, trend kriging and the fallback; kriging "
                              f"is kept unless more than {self.cfg['cv_margin']:.0%} worse than the fallback"),
                "candidates": self.candidates, "trend": self.trend,
                "variogram": self.variogram.to_dict() if self.variogram else None, "cv": self.cv,
                "std_factor": self.std_factor,
                "cv_models": self.cv_models, "max_distance_ft": self.max_distance_ft,
                "points": [{"x": p.x, "y": p.y, "z": p.z, "refs": p.refs} for p in self.points]}


def _kriging_fits(pts: list[Point], cfg: dict, drift: str):
    """{kind: LOO stats + variogram}, {kind: (Variogram, kriging)} for one drift."""
    try:
        base = residuals(pts, fit_trend(pts, drift)) if drift != "constant" else pts
    except ValueError:
        return {}, {}
    bins = empirical_variogram(base, cfg["bins"])
    models, fits = {}, {}
    for kind in KINDS:
        vg = fit_variogram(bins, kind)
        if vg is None or vg.psill <= 0:
            continue
        try:
            k = Kriging(pts, vg) if drift == "constant" else UniversalKriging(pts, vg, drift)
        except ValueError:
            continue
        errs, variances = k.leave_one_out()
        models[kind] = _stats(errs, variances) | {"variogram": vg.to_dict()}
        fits[kind] = (vg, k)
    return models, fits


def _trend_report(pts: list[Point], k: UniversalKriging, used: bool) -> dict:
    gx, gy = k.gradient()
    ols = fit_trend(pts, "linear")
    mean = sum(p.z for p in pts) / len(pts)
    sst = sum((p.z - mean) ** 2 for p in pts)
    sse = sum((p.z - ols(p.x, p.y)) ** 2 for p in pts)
    return {"drift": "linear", "used": used, **dip(gx, gy),
            "variance_explained": 1 - sse / sst if sst > 0 else None, "inferred": True,
            "note": "generalized least-squares drift of the trend kriging; variance explained by a least-squares plane"}


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
    candidates = {"fallback": {"rmse": cv.get("fallback", {}).get("rmse"), "chosen": False}}
    if n < cfg["min_points_kriging"]:
        candidates["fallback"]["chosen"] = True
        return Surface(pts, cfg, fallback, f"fewer than {cfg['min_points_kriging']} points for a variogram",
                       cv=cv, candidates=candidates)
    cv_models, chosen = {}, {}
    for method, drift in (("kriging", "constant"), ("trend_kriging", "linear")):
        models, fits = _kriging_fits(pts, cfg, drift)
        if not fits:
            candidates[method] = {"rmse": None, "chosen": False, "reason": "no variogram model could be fitted"}
            continue
        kind = min(models, key=lambda k: models[k]["rmse"])
        cv_models[method] = models
        cv[method] = {k: v for k, v in models[kind].items() if k != "variogram"}
        chosen[method] = (kind, *fits[kind])
        candidates[method] = {"rmse": cv[method]["rmse"], "chosen": False, "variogram": kind}
    trend = None
    if "trend_kriging" in chosen:
        trend = _trend_report(pts, chosen["trend_kriging"][2], used=False)
    if not chosen:
        candidates["fallback"]["chosen"] = True
        return Surface(pts, cfg, fallback, "no variogram model could be fitted", cv=cv, cv_models=cv_models,
                       trend=trend, candidates=candidates)
    best = min(chosen, key=lambda m: cv[m]["rmse"])
    kind, vg, krig = chosen[best]
    rmse, other = cv[best]["rmse"], cv.get("fallback", {}).get("rmse")
    if other is not None and rmse > (1 + cfg["cv_margin"]) * other:
        candidates["fallback"]["chosen"] = True
        reason = (f"{LABELS[best]} cross-validates worse than the fallback by more than "
                  f"{cfg['cv_margin']:.0%} (RMSE {rmse:.2f} vs {other:.2f} ft)")
        return Surface(pts, cfg, fallback, reason, vg, None, cv, cv_models, trend, candidates)
    candidates[best]["chosen"] = True
    if trend is not None:
        trend["used"] = best == "trend_kriging"
    others = ", ".join(f"{LABELS.get(m, m)} {c['rmse']:.2f}" for m, c in candidates.items()
                       if m != best and c.get("rmse") is not None)
    lead = ("lowest leave-one-out RMSE" if other is None or rmse <= other
            else f"leave-one-out RMSE within {cfg['cv_margin']:.0%} of the fallback")
    reason = f"{LABELS[best]}, {kind} variogram: {lead} ({rmse:.2f} ft" + (f"; {others} ft" if others else "") + ")"
    return Surface(pts, cfg, best, reason, vg, krig, cv, cv_models, trend, candidates)
