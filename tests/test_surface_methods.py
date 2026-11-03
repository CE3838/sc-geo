"""model/surface_methods.py: experimental interpolators compared by leave-one-out cross-validation.

Nothing here changes model/surfaces.build(); these methods are only measured (docs/interpolation.md).
"""

import math
import random

import pytest

from model import surface_methods as sm
from model import surfaces


def tilted(x, y):
    # A seaward-dipping surface (about 10 ft per mile to the south-east) with gentle relief on it.
    return -40.0 - 0.0019 * x - 0.0019 * y + 6.0 * math.sin(x / 2500.0) * math.cos(y / 3000.0)


def stretched(x, y):
    # Ridges that run north-east: long range along N45E, short across it.
    u = (x + y) / math.sqrt(2)
    v = (x - y) / math.sqrt(2)
    return 10.0 * math.sin(v / 1500.0) + 2.0 * math.sin(u / 9000.0)


def scatter(n, f, seed=1, size=20000.0):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        x, y = rnd.uniform(0, size), rnd.uniform(0, size)
        out.append(surfaces.Point(x, y, f(x, y), ref=f"p{i}"))
    return out


def test_universal_kriging_leave_one_out_shortcut_equals_refitting():
    pts = scatter(18, tilted, seed=3)
    vg = surfaces.Variogram("exponential", nugget=0.5, psill=20.0, range=6000.0)
    k = sm.UniversalKriging(pts, vg, drift="linear")
    errs, variances = k.leave_one_out()
    for i in (0, 9, 17):
        rest = sm.UniversalKriging(pts[:i] + pts[i + 1:], vg, drift="linear")
        est, var = rest.predict(pts[i].x, pts[i].y)
        assert errs[i] == pytest.approx(pts[i].z - est, abs=1e-6)
        assert variances[i] == pytest.approx(var, rel=1e-6)


def test_constant_drift_is_ordinary_kriging():
    pts = scatter(15, tilted, seed=4)
    vg = surfaces.Variogram("spherical", nugget=1.0, psill=50.0, range=8000.0)
    ok = surfaces.Kriging(pts, vg)
    uk = sm.UniversalKriging(pts, vg, drift="constant")
    assert uk.predict(5000.0, 7000.0) == pytest.approx(ok.predict(5000.0, 7000.0), rel=1e-9, abs=1e-9)


def test_linear_drift_reproduces_a_plane_exactly():
    pts = scatter(12, lambda x, y: 3.0 - 0.002 * x + 0.001 * y, seed=5)
    vg = surfaces.Variogram("exponential", 0.0, 1.0, 5000.0)
    est, _ = sm.UniversalKriging(pts, vg, drift="linear").predict(31000.0, -4000.0)  # far outside the data
    assert est == pytest.approx(3.0 - 0.002 * 31000.0 - 0.001 * 4000.0, abs=1e-6)


def test_trend_fit_and_residuals():
    pts = scatter(30, lambda x, y: 7.0 + 0.003 * x - 0.001 * y, seed=6)
    trend = sm.fit_trend(pts, "linear")
    assert trend(1000.0, 2000.0) == pytest.approx(7.0 + 3.0 - 2.0, abs=1e-6)
    assert all(abs(p.z) < 1e-6 for p in sm.residuals(pts, trend))


def test_detrended_kriging_beats_ordinary_kriging_on_a_dipping_surface():
    pts = scatter(60, tilted, seed=7)
    rows = {r["method"]: r for r in sm.compare(pts, methods=("current", "ok", "uk_linear"))}
    assert rows["uk_linear"]["rmse"] < rows["ok"]["rmse"]
    assert all(r["n"] == len(pts) for r in rows.values())


def test_anisotropy_search_finds_the_ridge_direction():
    pts = scatter(70, stretched, seed=8)
    fit = sm.fit_anisotropy(pts, drift="constant")
    # Azimuth of the long axis, degrees clockwise from north, folded to 0-180: N45E.
    assert min(abs(fit["azimuth_deg"] - 45.0), abs(fit["azimuth_deg"] - 225.0)) <= 15.0
    assert fit["ratio"] >= 2.0
    iso = {r["method"]: r for r in sm.compare(pts, methods=("ok",))}["ok"]
    assert fit["cv"]["rmse"] < iso["rmse"]


def test_compare_reports_the_current_method_as_build_does():
    pts = scatter(40, tilted, seed=9)
    row = {r["method"]: r for r in sm.compare(pts, methods=("current",))}["current"]
    s = surfaces.build(pts)
    key = s.method if s.method in surfaces.KRIGING_METHODS else "fallback"
    assert row["detail"].startswith(s.method)
    assert row["rmse"] == pytest.approx(s.cv[key]["rmse"], rel=1e-9)
    assert set(row) >= {"method", "n", "rmse", "bias", "mae", "msse", "detail"}


def test_stats_bias_is_mean_error():
    st = sm.stats([1.0, -3.0, 2.0])
    assert st["bias"] == pytest.approx(0.0) and st["rmse"] == pytest.approx(math.sqrt(14 / 3))


def _sv(value, page=3, **extra):
    return {"value": value, "source_id": "ngmdb:1", "page": page, "extraction_method": "llm", "confidence": 0.8,
            "inferred": False, "locator": None, **extra}


def _depth(ft):
    return _sv(f"{ft} feet", normalized={"min_ft": ft, "max_ft": ft, "unit": "feet", "approximate": False})


def _hole(lat, lon, elev, intervals, **extra):
    loc = _sv("lat/long", derived_coordinates={"value": {"lat": lat, "lon": lon}, "source_id": "ngmdb:1", "page": 3,
                                                "extraction_method": "inference", "confidence": 0.7, "inferred": True,
                                                "locator": None})
    el = _sv(f"{elev} ft", navd88={"value": {"min_ft": elev, "max_ft": elev}, "source_id": "ngmdb:1", "page": 3,
                                   "extraction_method": "datum_conversion", "confidence": 0.6, "inferred": True,
                                   "locator": None})
    ivs = [{"top": _depth(t), "bottom": _depth(b), "unit": _sv(u, normalized={"canonical": u})} for t, b, u in intervals]
    return {"kind": "auger_hole", "location": loc, "elevation": el, "intervals": ivs, **extra}


def test_contact_points_from_logged_holes():
    doc = {"observations": [
        _hole(32.8, -80.0, 20.0, [(0, 4, "Wando"), (4, 9, "Wando"), (9, 30, "Marks Head")]),
        _hole(32.9, -80.1, 15.0, [(0, 12, "Marks Head")]),   # unit at the surface: no buried top
        {**_hole(32.7, -80.0, 10.0, [(0, 5, "Wando"), (5, 8, "Marks Head")]), "location": None},  # no coordinates
    ]}
    sets = sm.contact_points({"data/extracted/x.json": doc})
    tops = sets[("marks head", "top")]
    assert len(tops) == 1 and tops[0].z == pytest.approx(20.0 - 9.0)
    ref = tops[0].refs[0]
    assert ref["inferred"] is True and ref["source_id"] == "ngmdb:1" and ref["path"] == "observations[0].intervals[2].top"
    land = sets[("land surface", "ngmdb:1")]
    assert sorted(p.z for p in land) == [15.0, 20.0]
    assert ("wando", "top") not in sets  # Wando is at the land surface in the only hole that logs it


def test_contact_points_skip_intervals_given_as_elevations():
    hole = _hole(32.8, -80.0, 20.0, [(0, 4, "Wando"), (4, 9, "Marks Head")])
    hole["intervals"][1]["top"]["value"] = "4 feet above sea level"
    sets = sm.contact_points({"x": {"observations": [hole]}})
    assert ("marks head", "top") not in sets


def test_build_defaults_are_unchanged():
    assert surfaces.DEFAULTS["min_points_kriging"] == 10 and surfaces.DEFAULTS["min_std_ft"] == 0.3
    assert sm.UniversalKriging is surfaces.UniversalKriging   # the research code measures what build() runs


def test_nested_anisotropy_chooses_without_the_held_out_point():
    pts = scatter(16, stretched, seed=10)
    errs = sm.nested_anisotropy_errors(pts, "constant", azimuths=(0, 45, 90, 135), ratios=(1.0, 3.0))
    assert len(errs) == len(pts)
    # Fold 0 by hand.
    rest = pts[1:]
    fit = sm.fit_anisotropy(rest, "constant", (0, 45, 90, 135), (1.0, 3.0))
    v = fit["variogram"]
    vg = surfaces.Variogram(v["kind"], v["nugget"], v["partial_sill"], v["range_ft"])
    (tp,) = sm.transform([pts[0]], fit["azimuth_deg"], fit["ratio"])
    est, _ = sm.UniversalKriging(sm.transform(rest, fit["azimuth_deg"], fit["ratio"]), vg, "constant").predict(tp.x, tp.y)
    assert errs[0] == pytest.approx(pts[0].z - est)


def test_crossings_counts_nodes_where_the_lower_surface_comes_out_above():
    up = surfaces.build([surfaces.Point(x, y, 0.0) for x in (0, 5000, 10000) for y in (0, 5000, 10000)])
    lo = surfaces.build([surfaces.Point(x, y, -10.0 + 0.002 * x) for x in (0, 5000, 10000) for y in (0, 5000, 10000)])
    c = sm.crossings(up, lo, step_ft=1000.0)
    assert c["nodes"] > 0 and 0 < c["crossed"] < c["nodes"] and c["worst_ft"] == pytest.approx(10.0, abs=0.5)
