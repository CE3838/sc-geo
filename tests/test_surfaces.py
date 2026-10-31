"""model/surfaces.py: surfaces from point elevations, with uncertainty, tested on known surfaces."""

import math
import random

import pytest

from model import coords, surfaces


def plane(x, y):
    return 5.0 + 0.01 * x - 0.02 * y


def bump(x, y):
    return -60.0 + 25.0 * math.sin(x / 3000.0) * math.cos(y / 4000.0)


def scatter(n, f, seed=1, size=20000.0, noise=0.0):
    rnd = random.Random(seed)
    pts = []
    for i in range(n):
        x, y = rnd.uniform(0, size), rnd.uniform(0, size)
        pts.append(surfaces.Point(x, y, f(x, y) + (rnd.gauss(0, noise) if noise else 0.0), ref=f"p{i}"))
    return pts


# --- linear algebra ------------------------------------------------------------

def test_solve_and_inverse():
    a = [[4.0, 1.0, 2.0], [1.0, 3.0, 0.0], [2.0, 0.0, 5.0]]
    x = surfaces.solve(a, [7.0, 4.0, 7.0])
    assert x == pytest.approx([1.0, 1.0, 1.0])
    inv = surfaces.inverse(a)
    for i in range(3):
        for j in range(3):
            assert sum(a[i][k] * inv[k][j] for k in range(3)) == pytest.approx(1.0 if i == j else 0.0, abs=1e-12)
    with pytest.raises(ValueError):
        surfaces.solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])


# --- variograms ---------------------------------------------------------------

@pytest.mark.parametrize("kind", ["spherical", "exponential", "gaussian"])
def test_variogram_fit_recovers_a_known_model(kind):
    true = surfaces.Variogram(kind, nugget=2.0, psill=10.0, range=5000.0)
    lags = [250.0 * (i + 1) for i in range(30)]
    bins = [(h, true.gamma(h), 50) for h in lags]
    fit = surfaces.fit_variogram(bins, kind)
    assert fit.kind == kind
    assert fit.nugget == pytest.approx(2.0, abs=0.3) and fit.psill == pytest.approx(10.0, rel=0.08)
    assert fit.range == pytest.approx(5000.0, rel=0.15) and fit.r2 > 0.99


def test_empirical_variogram_bins_pairs():
    pts = scatter(30, bump)
    bins = surfaces.empirical_variogram(pts)
    assert len(bins) >= 6 and all(n >= 3 for _, _, n in bins)
    assert bins == sorted(bins) and all(g >= 0 for _, g, _ in bins)


# --- kriging --------------------------------------------------------------------

def test_leave_one_out_shortcut_equals_refitting():
    pts = scatter(15, bump, seed=3)
    vg = surfaces.Variogram("spherical", nugget=1.0, psill=200.0, range=8000.0)
    k = surfaces.Kriging(pts, vg)
    errs, vars_ = k.leave_one_out()
    for i in (0, 7, 14):
        rest = surfaces.Kriging(pts[:i] + pts[i + 1:], vg)
        est, var = rest.predict(pts[i].x, pts[i].y)
        assert errs[i] == pytest.approx(pts[i].z - est, abs=1e-6)
        assert vars_[i] == pytest.approx(var, rel=1e-6)


def test_kriging_is_exact_at_data_and_less_certain_far_away():
    pts = scatter(20, bump, seed=4)
    k = surfaces.Kriging(pts, surfaces.Variogram("exponential", 0.0, 200.0, 9000.0))
    est, var = k.predict(pts[0].x, pts[0].y)
    assert est == pytest.approx(pts[0].z, abs=1e-6) and var == pytest.approx(0.0, abs=1e-6)
    near = k.predict(pts[0].x + 100, pts[0].y)[1]
    far = k.predict(pts[0].x + 4000, pts[0].y + 4000)[1]
    assert 0 < near < far


def test_smooth_surface_uses_kriging_and_beats_idw():
    pts = scatter(60, bump, seed=5)
    s = surfaces.build(pts)
    assert s.method in surfaces.KRIGING_METHODS and s.variogram.kind in ("spherical", "exponential", "gaussian")
    assert set(s.cv) >= {"kriging", "trend_kriging", "idw"} and s.cv[s.method]["rmse"] < s.cv["idw"]["rmse"]
    assert s.std_factor < 1  # the raw kriging sd is pessimistic here; calibration narrows it
    rnd = random.Random(9)
    errs, stds = [], []
    for _ in range(100):
        x, y = rnd.uniform(3000, 17000), rnd.uniform(3000, 17000)
        e = s.estimate(x, y)
        assert e["method"] == s.method and e["std"] > 0 and e["std_kind"].startswith("kriging standard deviation")
        errs.append(e["value"] - bump(x, y))
        stds.append(e["std"])
    rmse = math.sqrt(sum(x * x for x in errs) / len(errs))
    assert rmse < 2.5  # the surface spans 50 ft
    # The reported uncertainty is honest on points it never saw: about 95% within 2 sd,
    # and not so wide as to be useless.
    cover = sum(abs(e) <= 2 * sd for e, sd in zip(errs, stds)) / len(errs)
    assert 0.85 <= cover <= 1.0
    assert sum(stds) / len(stds) < 3 * rmse


def test_calibration_factor_is_the_cross_validation_msse_bounded():
    s = surfaces.build(scatter(60, bump, seed=5))
    lo, hi = surfaces.DEFAULTS["msse_bounds"]
    assert s.std_factor == pytest.approx(math.sqrt(min(max(s.cv[s.method]["msse"], lo), hi)))
    e = s.estimate(9000.0, 9000.0)
    assert e["std"] == pytest.approx(max(e["std_raw"] * s.std_factor, surfaces.DEFAULTS["min_std_ft"]))


def test_uncertainty_never_below_reading_precision():
    s = surfaces.build(scatter(60, bump, seed=5))
    p = s.points[0]
    e = s.estimate(p.x, p.y)  # at a data point kriging is exact, but elevations are printed to about a foot
    assert e["value"] == pytest.approx(p.z, abs=1e-6) and e["std"] == surfaces.DEFAULTS["min_std_ft"]


def test_kriging_is_compared_with_the_fallback_on_the_same_points():
    s = surfaces.build(scatter(40, plane, seed=2))
    fb = s.cv["fallback"]
    assert fb["n"] == s.cv["kriging"]["n"] == len(s.points)   # natural neighbour inside, IDW on the hull
    assert s.cv["natural_neighbor"]["n"] < len(s.points)


def test_model_choice_is_by_cross_validation():
    s = surfaces.build(scatter(60, bump, seed=5))
    rmses = {k: v["rmse"] for k, v in s.cv_models[s.method].items()}
    assert set(rmses) == {"spherical", "exponential", "gaussian"}
    assert s.variogram.kind == min(rmses, key=rmses.get)


# --- fallbacks -----------------------------------------------------------------------

def test_natural_neighbor_reproduces_a_plane_exactly():
    pts = scatter(8, plane, seed=6)
    nn = surfaces.NaturalNeighbor(pts)
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    for dx, dy in ((0, 0), (300, -200), (-500, 400)):
        assert nn.predict(cx + dx, cy + dy) == pytest.approx(plane(cx + dx, cy + dy), abs=1e-6)
    assert nn.predict(pts[2].x, pts[2].y) == pytest.approx(pts[2].z)
    assert nn.predict(-50000.0, -50000.0) is None  # outside the hull


def test_too_few_points_fall_back_to_natural_neighbor_then_idw():
    pts = scatter(6, plane, seed=7)
    s = surfaces.build(pts)
    assert s.method == "natural_neighbor" and "fewer than" in s.reason
    cx = sum(p.x for p in pts) / 6
    cy = sum(p.y for p in pts) / 6
    e = s.estimate(cx, cy)
    assert e["method"] == "natural_neighbor" and e["value"] == pytest.approx(plane(cx, cy), abs=1e-6)
    assert e["std"] is not None and e["std_kind"] == "leave-one-out RMSE"
    hull_x = max(p.x for p in pts)
    out = s.estimate(hull_x + 500, cy)
    assert out["method"] == "idw" and out["extrapolated"] is True and out["value"] is not None


def test_no_spatial_structure_is_judged_by_cross_validation_not_by_the_variogram():
    # White noise: the variogram is almost all nugget. There is no fit gate any more; the method
    # is whichever cross-validates best under the selection rule.
    rnd = random.Random(8)
    pts = [surfaces.Point(rnd.uniform(0, 20000), rnd.uniform(0, 20000), rnd.gauss(0, 10)) for _ in range(40)]
    s = surfaces.build(pts)
    assert s.method == expected_choice(s)
    assert "min_r2" not in surfaces.DEFAULTS and "min_structure" not in surfaces.DEFAULTS


# --- never extrapolate silently ---------------------------------------------------

def test_beyond_max_distance_gives_no_value():
    pts = scatter(30, bump, seed=10)
    s = surfaces.build(pts, {"max_distance_ft": 2000.0})
    e = s.estimate(60000.0, 60000.0)
    assert e["value"] is None and e["std"] is None and "beyond" in e["reason"]
    assert e["nearest_ft"] > 2000.0


def test_default_max_distance_comes_from_point_spacing():
    pts = scatter(30, bump, seed=10)
    s = surfaces.build(pts)
    assert 0 < s.max_distance_ft < 20000.0
    assert s.estimate(-30000.0, -30000.0)["value"] is None


def test_every_estimate_says_how_it_was_made():
    s = surfaces.build(scatter(30, bump, seed=11))
    e = s.estimate(10000.0, 10000.0)
    assert {"value", "std", "std_kind", "method", "nearest_ft", "inside_hull", "extrapolated", "n_points"} <= set(e)
    assert e["inside_hull"] is True and e["extrapolated"] is False


def test_one_point():
    s = surfaces.build([surfaces.Point(0.0, 0.0, -50.0, ref="only")], {"max_distance_ft": 1000.0})
    e = s.estimate(10.0, 10.0)
    assert e["value"] == -50.0 and e["std"] is None and "cross-validation" in e["reason"]
    assert s.estimate(5000.0, 0.0)["value"] is None


def test_coincident_points_are_averaged_and_kept_in_provenance():
    pts = scatter(12, plane, seed=12) + [surfaces.Point(100.0, 100.0, -10.0, ref="a"),
                                         surfaces.Point(100.0, 100.0, -14.0, ref="b")]
    s = surfaces.build(pts)
    merged = [p for p in s.points if p.x == 100.0 and p.y == 100.0]
    assert len(merged) == 1 and merged[0].z == -12.0 and set(merged[0].refs) == {"a", "b"}
    prov = s.provenance()
    assert prov["method"] == s.method and len(prov["points"]) == 13 and prov["inferred"] is True


def test_points_from_latlon_use_state_plane_feet():
    p = surfaces.point_from_latlon(32.78, -79.95, -62.0, ref="x")
    e, n = coords.latlon_to_state_plane(32.78, -79.95)
    assert (p.x, p.y, p.z) == pytest.approx((e, n, -62.0))


# --- regional dip (trend kriging) and the selection rule ------------------------------

def expected_choice(s):
    """The selection rule, recomputed from the cross-validation build() reports."""
    krig = [m for m in surfaces.KRIGING_METHODS if m in s.cv]
    if not krig:
        return "natural_neighbor" if len(s.points) >= 3 else "idw"
    best = min(krig, key=lambda m: s.cv[m]["rmse"])
    fb = s.cv["fallback"]["rmse"]
    if s.cv[best]["rmse"] > (1 + surfaces.DEFAULTS["cv_margin"]) * fb:
        return "natural_neighbor"
    return best


def dipping(x, y, ft_per_mile=10.0, azimuth=135.0):
    """A plane dipping `ft_per_mile` toward `azimuth` (clockwise from north) with gentle relief on it."""
    g = ft_per_mile / 5280.0
    a = math.radians(azimuth)
    return -40.0 - g * (x * math.sin(a) + y * math.cos(a)) + 2.0 * math.sin(x / 2500.0) * math.cos(y / 3000.0)


@pytest.mark.parametrize("azimuth", [135.0, 200.0])
def test_trend_kriging_recovers_the_regional_dip(azimuth):
    pts = scatter(50, lambda x, y: dipping(x, y, 10.0, azimuth), seed=21, size=40000.0)
    s = surfaces.build(pts)
    assert s.method == "trend_kriging"
    t = s.provenance()["trend"]
    assert t["drift"] == "linear" and t["used"] is True
    assert t["dip_ft_per_mile"] == pytest.approx(10.0, rel=0.1)
    assert abs((t["dip_azimuth_deg"] - azimuth + 180) % 360 - 180) <= 5.0
    assert t["dip_direction"].startswith("S")
    assert s.cv["trend_kriging"]["rmse"] < s.cv["kriging"]["rmse"]
    e = s.estimate(20000.0, 20000.0)
    assert e["method"] == "trend_kriging" and e["value"] == pytest.approx(dipping(20000.0, 20000.0, 10.0, azimuth), abs=1.5)
    assert e["std"] >= surfaces.DEFAULTS["min_std_ft"]


def test_dip_direction_is_written_as_a_quadrant_bearing():
    assert surfaces.bearing(0.0) == "N0°E" and surfaces.bearing(152.0) == "S28°E"
    assert surfaces.bearing(208.0) == "S28°W" and surfaces.bearing(300.0) == "N60°W"
    d = surfaces.dip(0.0, 1.0 / 5280.0)            # rising to the north: dips 1 ft per mile due south
    assert d["dip_ft_per_mile"] == pytest.approx(1.0) and d["dip_azimuth_deg"] == pytest.approx(180.0)


def test_trend_kriging_leave_one_out_is_exact():
    pts = scatter(18, lambda x, y: dipping(x, y), seed=22)
    vg = surfaces.Variogram("exponential", nugget=0.5, psill=4.0, range=6000.0)
    k = surfaces.UniversalKriging(pts, vg, drift="linear")
    errs, variances = k.leave_one_out()
    for i in (0, 9, 17):
        est, var = surfaces.UniversalKriging(pts[:i] + pts[i + 1:], vg, drift="linear").predict(pts[i].x, pts[i].y)
        assert errs[i] == pytest.approx(pts[i].z - est, abs=1e-6) and variances[i] == pytest.approx(var, rel=1e-6)


@pytest.mark.parametrize("f,seed", [(bump, 5), (plane, 2), (lambda x, y: dipping(x, y), 23)])
def test_method_is_chosen_by_leave_one_out_rmse(f, seed):
    s = surfaces.build(scatter(40, f, seed=seed, noise=0.5))
    assert s.method == expected_choice(s)
    prov = s.provenance()
    assert set(prov["candidates"]) >= {"kriging", "trend_kriging", "fallback"}
    assert prov["candidates"][s.method if s.method in surfaces.KRIGING_METHODS else "fallback"]["chosen"] is True


def test_a_poor_variogram_fit_no_longer_rejects_kriging(monkeypatch):
    real = surfaces.fit_variogram

    def poor(bins, kind):
        vg = real(bins, kind)
        if vg is not None:
            vg.r2 = 0.05       # the old rule fell back below r2 0.3
        return vg
    monkeypatch.setattr(surfaces, "fit_variogram", poor)
    s = surfaces.build(scatter(60, bump, seed=5))
    assert s.method in surfaces.KRIGING_METHODS and s.variogram.r2 == 0.05
    assert "r2" not in s.reason


def test_fallback_wins_only_when_kriging_cross_validates_worse_by_more_than_the_margin(monkeypatch):
    pts = scatter(40, bump, seed=5)
    s = surfaces.build(pts, {"cv_margin": -0.99})     # any kriging error above 1% of the fallback's loses
    assert s.method == "natural_neighbor" and "worse than the fallback" in s.reason
    assert s.estimate(9000.0, 9000.0)["std_kind"] == "leave-one-out RMSE"


def test_too_few_points_for_trend_kriging_report_no_trend():
    s = surfaces.build(scatter(6, plane, seed=7))
    assert s.provenance()["trend"] is None and "trend_kriging" not in s.cv
