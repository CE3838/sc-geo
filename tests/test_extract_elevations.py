"""extract/elevations.py: a derived NAVD88 value next to every elevation with a usable datum."""

import pytest

from extract import elevations
from model import vdatum
from model.provenance import ExtractionMethod, StoredValue
from tests import geotiff_writer

FT = 0.3048
SHIFT_M = -0.3  # a uniform synthetic grid: NAVD88 = NGVD29 - 0.3 m


@pytest.fixture
def grid(tmp_path):
    p = tmp_path / "grid.tif"
    geotiff_writer.write(p, [[SHIFT_M] * 5 for _ in range(5)], -81.0, 34.0, 0.5, 0.5)
    return vdatum.read_geotiff(p)


CFG = {"msl_as_ngvd29_before": 1991, "fallback_ngvd29_to_navd88_ft": None, "approximate_factor": 0.9}


def s(value, page=2, units=None, **kw):
    e = {"value": value, "source_id": "ngmdb:9", "page": page, "extraction_method": "llm", "confidence": 0.85,
         "inferred": False, "locator": None, "quote": f"q {value}", "quote_match": "exact"}
    if units:
        e["units"] = units
    return {**e, **kw}


def loc(lat, lon, page=2):
    return s(f"{lat}, {lon}", page, derived_coordinates={"value": {"lat": lat, "lon": lon}})


def sections():
    return {
        "observations": [
            {"kind": "well", "elevation": s("42 ft"), "datum": s("NGVD 29", normalized="NGVD29", page=3),
             "location": loc(32.8, -79.9), "depth_reference": s("elevation"),
             "intervals": [{"top": s(-10, units="ft"), "bottom": s("-30 ft")}]},
            {"kind": "boring", "elevation": s("12 ft above NAVD 88")},                       # datum in the text
            {"kind": "boring", "elevation": s("15 ft"), "location": loc(32.8, -79.9),
             "intervals": [{"top": s("0 ft")}]},                                               # depths: untouched
        ],
        "surfaces": [
            {"surface": s("top of Cooper Marl"), "elevation": s(-62, units="ft"),
             "datum": s("NGVD 29", normalized="NGVD29"), "location": loc(32.75, -79.98)},
            {"elevation": s("-62 ft"), "datum": s("NGVD 29", normalized="NGVD29")},           # no location
            {"elevation": s("120 ft below sea level"), "location": loc(32.8, -79.9)},       # MSL in the text
            {"depth": s("35 ft"), "datum": s("land surface", normalized="land surface")},
        ],
        "groundwater": [
            {"head": s("minimum of –97 ft"), "location": loc(32.8, -79.9)},
            {"head": s("12 ft below land surface", normalized={"min_ft": 12.0, "max_ft": 12.0,
                                                               "relative_to": "land surface"})},
        ],
        "sections": [{
            "datum": s("sea level", normalized="MSL"),
            "start": {"location": loc(32.9, -80.2)}, "end": {"coordinates": loc(32.7, -79.9)},
            "units_along": [{"top_elevation": s("-40 ft"), "base_elevation": s("-110 ft")}],
        }],
    }


def test_ngvd29_values_get_a_navd88_value_with_provenance(grid):
    sec = sections()
    stats = elevations.attach_navd88(sec, 1985, grid, CFG)
    n = sec["surfaces"][0]["elevation"]["navd88"]
    sv = StoredValue.from_dict(n)
    assert sv.inferred and sv.extraction_method is ExtractionMethod.DATUM_CONVERSION
    assert sv.page == 2 and sv.source_id == "ngmdb:9"
    assert n["value"]["min_ft"] == pytest.approx(-62 + SHIFT_M / FT)
    assert n["from_datum"] == "NGVD29" and n["datum_from"] == "datum field" and n["datum_page"] == 2
    assert n["confidence"] == round(0.85 * 0.8, 3)
    assert sec["surfaces"][0]["elevation"]["value"] == -62  # the reading is unchanged
    assert stats["converted"] >= 5


def test_observation_elevation_and_elevation_intervals(grid):
    sec = sections()
    elevations.attach_navd88(sec, 1985, grid, CFG)
    obs = sec["observations"][0]
    assert obs["elevation"]["navd88"]["value"]["min_ft"] == pytest.approx(42 + SHIFT_M / FT)
    assert obs["elevation"]["navd88"]["datum_page"] == 3
    iv = obs["intervals"][0]
    assert iv["top"]["navd88"]["value"]["min_ft"] == pytest.approx(-10 + SHIFT_M / FT)
    assert iv["bottom"]["navd88"]["value"]["min_ft"] == pytest.approx(-30 + SHIFT_M / FT)
    assert sec["observations"][1]["elevation"]["navd88"]["value"]["min_ft"] == 12.0  # NAVD88 already
    assert sec["observations"][1]["elevation"]["navd88"]["datum_from"] == "value text"
    assert "navd88" not in sec["observations"][2]["intervals"][0]["top"]           # a depth, not an elevation
    # no datum stated: kept as printed, approximate, lower confidence
    e = sec["observations"][2]["elevation"]["navd88"]
    assert e["value"]["min_ft"] == 15.0 and e["approximate"] is True
    assert e["confidence"] == round(0.85 * 0.8 * 0.9, 3)


def test_skips_are_counted_with_reasons(grid):
    sec = sections()
    stats = elevations.attach_navd88(sec, 1985, grid, CFG)
    assert "navd88" not in sec["surfaces"][1]["elevation"]
    assert any("location" in r for r in stats["skipped"])
    assert "navd88" not in sec["surfaces"][3]["depth"]
    assert "navd88" not in sec["groundwater"][1]["head"]
    assert any("land surface" in r for r in stats["skipped"])


def test_msl_before_and_after_navd88(grid):
    sec = sections()
    elevations.attach_navd88(sec, 1985, grid, CFG)
    m = sec["surfaces"][2]["elevation"]["navd88"]
    assert m["value"]["min_ft"] == pytest.approx(-120 + SHIFT_M / FT) and m["approximate"] is True
    assert m["datum_from"] == "value text"
    sec2 = sections()
    elevations.attach_navd88(sec2, 2005, grid, CFG)
    assert "navd88" not in sec2["surfaces"][2]["elevation"]


def test_heads_keep_bounds_and_sections_use_their_ends(grid):
    sec = sections()
    elevations.attach_navd88(sec, 1985, grid, CFG)
    h = sec["groundwater"][0]["head"]["navd88"]
    assert h["value"]["max_ft"] is None and h["approximate"] is True  # datum not stated
    u = sec["sections"][0]["units_along"][0]
    t = u["top_elevation"]["navd88"]
    assert t["value"]["min_ft"] == pytest.approx(-40 + SHIFT_M / FT)
    assert t["datum_from"] == "section datum" and t["location_from"] == "section ends (midpoint)"
    assert u["base_elevation"]["navd88"]["value"]["min_ft"] == pytest.approx(-110 + SHIFT_M / FT)


def test_without_grid_ngvd29_is_skipped_and_navd88_still_passes():
    sec = sections()
    stats = elevations.attach_navd88(sec, 1985, None, CFG)
    assert "navd88" not in sec["surfaces"][0]["elevation"]
    assert any("harvest.vertcon" in r for r in stats["skipped"])
    assert sec["observations"][1]["elevation"]["navd88"]["value"]["min_ft"] == 12.0


def test_idempotent_and_stale_values_removed(grid):
    sec = sections()
    elevations.attach_navd88(sec, 1985, grid, CFG)
    first = repr(sec)
    elevations.attach_navd88(sec, 1985, grid, CFG)
    assert repr(sec) == first
    elevations.attach_navd88(sec, 1985, None, CFG)
    assert "navd88" not in sec["surfaces"][0]["elevation"]
