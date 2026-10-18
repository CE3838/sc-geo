"""The real NGVD29-to-NAVD88 grid, when harvest.vertcon has downloaded it (skipped otherwise, so CI stays offline).

Check values:
* File metadata (GDAL metadata in the GeoTIFF): source EPSG 7968 (NGVD29 height), target EPSG 5703
  (NAVD88 height), TYPE VERTICAL_OFFSET_VERTICAL_TO_VERTICAL, metres; PROJ applies it as
  NAVD88 = NGVD29 + offset.
* Expected size of the shift: about -0.8 to -1.1 ft on the South Carolina coast and about -1.0 ft at
  Charleston, the project engineer's working values for VERTCON in coastal South Carolina (2026-10).
  NGS's own VERTCON point computations (ngs.noaa.gov) could not be fetched from this environment, so
  these are a range check, not a point-by-point comparison with NGS output.
"""

import hashlib

import pytest

from harvest import vertcon
from model import vdatum

PATH = vertcon.grid_path()
pytestmark = pytest.mark.skipif(not PATH.exists(), reason="datum grid not downloaded (python -m harvest.vertcon)")
FT = 0.3048


@pytest.fixture(scope="module")
def grid():
    return vdatum.read_geotiff(PATH)


def test_file_is_the_pinned_one():
    assert hashlib.sha256(PATH.read_bytes()).hexdigest() == vertcon.CONFIG["grid_sha256"]


def test_extent_and_spacing(grid):
    # VERTCON eastern grid: nodes every 3 minutes from 89 W and 50 N.
    assert (grid.west, grid.north, grid.dx, grid.dy) == (-89.0, 50.0, 0.05, 0.05)
    assert (grid.ncols, grid.nrows) == (461, 521)


def test_metadata_says_ngvd29_to_navd88_in_metres():
    meta = PATH.read_bytes()
    assert b"<Item name=\"source_crs_epsg_code\">7968</Item>" in meta
    assert b"<Item name=\"target_crs_epsg_code\">5703</Item>" in meta
    assert b"VERTICAL_OFFSET_VERTICAL_TO_VERTICAL" in meta and b">metre<" in meta


@pytest.mark.parametrize("place,lat,lon", [
    ("Charleston", 32.7765, -79.9311), ("Mount Pleasant", 32.8323, -79.8284), ("Folly Beach", 32.6552, -79.9404),
    ("Summerville", 33.0185, -80.1756), ("Beaufort", 32.4316, -80.6698), ("Hilton Head Island", 32.2163, -80.7526),
    ("Georgetown", 33.3768, -79.2945), ("Myrtle Beach", 33.6891, -78.8867),
])
def test_coastal_south_carolina_is_about_minus_one_foot(grid, place, lat, lon):
    ft = grid.shift_m(lat, lon) / FT
    assert -1.1 <= ft <= -0.8, (place, ft)


def test_charleston_is_about_minus_one_foot(grid):
    assert grid.shift_m(32.7765, -79.9311) / FT == pytest.approx(-1.0, abs=0.05)


def test_shift_shrinks_inland(grid):
    coast = grid.shift_m(32.7765, -79.9311)
    midlands = grid.shift_m(34.0007, -81.0348)   # Columbia
    upstate = grid.shift_m(34.8526, -82.3940)    # Greenville
    assert coast < midlands < upstate < 0


def test_bilinear_returns_the_stored_value_at_a_node(grid):
    col, row = round((-80.0 - grid.west) / grid.dx), round((grid.north - 33.0) / grid.dy)
    node = grid.values[row * grid.ncols + col]
    assert grid.shift_m(33.0, -80.0) == pytest.approx(node, abs=1e-9)


def test_to_navd88_with_the_real_grid(grid):
    r, why = vdatum.to_navd88({"min_ft": -62.0, "max_ft": -62.0}, "NGVD29", 32.7533, -79.9781, 1985, grid,
                              vertcon.CONFIG)
    assert why is None and -63.1 <= r["min_ft"] <= -62.8 and "us_noaa_vertcone.tif" in r["conversion"]
