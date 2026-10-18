"""model/vdatum.py: NGVD29 -> NAVD88 from an official shift grid, with explicit fallbacks."""

import pytest

from model import vdatum
from tests import geotiff_writer

# A synthetic shift field (metres, NAVD88 minus NGVD29) that is linear, so bilinear
# interpolation must reproduce it exactly: s = -0.25 + 0.01 * (lon + 80) - 0.02 * (lat - 32).
WEST, NORTH, D = -81.0, 34.0, 0.25
LONS = [WEST + i * D for i in range(9)]       # -81 .. -79
LATS = [NORTH - j * D for j in range(9)]      # 34 .. 32 (north to south)


def field(lat, lon):
    return -0.25 + 0.01 * (lon + 80) - 0.02 * (lat - 32)


ROWS = [[field(lat, lon) for lon in LONS] for lat in LATS]


@pytest.mark.parametrize("opts", [
    dict(),                                                    # strips, uncompressed, PixelIsPoint
    dict(compression=8, predictor=3, tile=4),                  # PROJ-data style: deflate, float predictor, tiles
    dict(compression=8, pixel_is_point=False),                 # PixelIsArea corner tiepoint
    dict(byteorder=">", tile=16),                              # big-endian, one partial tile
])
def test_reads_geotiff_shift_grids(tmp_path, opts):
    p = tmp_path / "grid.tif"
    geotiff_writer.write(p, ROWS, WEST, NORTH, D, D, **opts)
    g = vdatum.read_geotiff(p)
    assert (g.ncols, g.nrows) == (9, 9)
    assert g.west == pytest.approx(WEST) and g.north == pytest.approx(NORTH)
    for lat, lon in ((32.0, -81.0), (34.0, -79.0), (32.7765, -79.9311), (33.1, -80.62)):
        assert g.shift_m(lat, lon) == pytest.approx(field(lat, lon), abs=1e-6)


def test_outside_grid_or_nodata_is_none(tmp_path):
    rows = [r[:] for r in ROWS]
    rows[4][4] = -9999.0
    p = tmp_path / "grid.tif"
    geotiff_writer.write(p, rows, WEST, NORTH, D, D, nodata=-9999.0)
    g = vdatum.read_geotiff(p)
    assert g.shift_m(35.0, -80.0) is None and g.shift_m(33.0, -82.0) is None
    assert g.shift_m(33.0, -80.0) is None            # a corner of the cell is nodata
    assert g.shift_m(33.6, -80.6) is not None


def test_longitudes_0_to_360(tmp_path):
    p = tmp_path / "grid.tif"
    geotiff_writer.write(p, ROWS, WEST + 360, NORTH, D, D)
    assert vdatum.read_geotiff(p).shift_m(33.1, -80.62) == pytest.approx(field(33.1, -80.62), abs=1e-6)


def test_not_a_tiff_is_an_error(tmp_path):
    p = tmp_path / "x.tif"
    p.write_bytes(b"not a tiff")
    with pytest.raises(ValueError):
        vdatum.read_geotiff(p)


# --- to_navd88 rules -----------------------------------------------------------

@pytest.fixture
def grid(tmp_path):
    p = tmp_path / "grid.tif"
    geotiff_writer.write(p, ROWS, WEST, NORTH, D, D)
    return vdatum.read_geotiff(p)


CFG = {"msl_as_ngvd29_before": 1991, "fallback_ngvd29_to_navd88_ft": None}
FT = 0.3048


def test_ngvd29_through_the_grid(grid):
    r, why = vdatum.to_navd88({"min_ft": -62.0, "max_ft": -62.0}, "NGVD29", 32.7533, -79.9781, 1985, grid, CFG)
    s = field(32.7533, -79.9781) / FT
    assert why is None and r["min_ft"] == pytest.approx(-62.0 + s) and r["shift_ft"] == pytest.approx(s)
    assert r["from_datum"] == "NGVD29" and r["approximate"] is False and "grid" in r["conversion"]


def test_navd88_unchanged_and_open_bounds_kept(grid):
    r, _ = vdatum.to_navd88({"min_ft": -97.0, "max_ft": None}, "NAVD88", None, None, 2010, grid, CFG)
    assert r["min_ft"] == -97.0 and r["max_ft"] is None and r["shift_ft"] == 0 and r["approximate"] is False


def test_msl_is_ngvd29_only_before_navd88(grid):
    r, _ = vdatum.to_navd88({"min_ft": 10.0, "max_ft": 10.0}, "MSL", 33.0, -80.0, 1975, grid, CFG)
    assert r["from_datum"] == "NGVD29" and r["approximate"] is True
    assert any("sea level" in a and "1975" in a for a in r["assumptions"])
    r, why = vdatum.to_navd88({"min_ft": 10.0, "max_ft": 10.0}, "MSL", 33.0, -80.0, 2001, grid, CFG)
    assert r is None and "sea level" in why
    r, why = vdatum.to_navd88({"min_ft": 10.0, "max_ft": 10.0}, "MSL", 33.0, -80.0, None, grid, CFG)
    assert r is None


def test_land_surface_stays_relative(grid):
    r, why = vdatum.to_navd88({"min_ft": 35.0, "max_ft": 35.0}, "land surface", 33.0, -80.0, 1985, grid, CFG)
    assert r is None and "land surface" in why


@pytest.mark.parametrize("datum", [None, "unknown"])
def test_no_datum_is_kept_as_approximate(grid, datum):
    r, _ = vdatum.to_navd88({"min_ft": 5.0, "max_ft": 5.0}, datum, 33.0, -80.0, 1985, grid, CFG)
    assert r["min_ft"] == 5.0 and r["approximate"] is True and r["from_datum"] is None
    assert any("not stated" in a for a in r["assumptions"])


def test_ngvd29_needs_a_location_and_a_grid(grid):
    r, why = vdatum.to_navd88({"min_ft": 1.0, "max_ft": 1.0}, "NGVD29", None, None, 1985, grid, CFG)
    assert r is None and "location" in why
    r, why = vdatum.to_navd88({"min_ft": 1.0, "max_ft": 1.0}, "NGVD29", 40.0, -80.0, 1985, grid, CFG)
    assert r is None and "outside" in why
    r, why = vdatum.to_navd88({"min_ft": 1.0, "max_ft": 1.0}, "NGVD29", 33.0, -80.0, 1985, None, CFG)
    assert r is None and "harvest.vertcon" in why


def test_configured_fallback_shift_is_approximate_and_named():
    cfg = {**CFG, "fallback_ngvd29_to_navd88_ft": -0.9, "fallback_source": "a cited constant"}
    r, _ = vdatum.to_navd88({"min_ft": 1.0, "max_ft": 1.0}, "NGVD29", None, None, 1985, None, cfg)
    assert r["min_ft"] == pytest.approx(0.1) and r["approximate"] is True and "a cited constant" in r["conversion"]


def test_load_grid_missing_file_is_none(tmp_path):
    assert vdatum.load_grid(tmp_path / "absent.tif") is None
