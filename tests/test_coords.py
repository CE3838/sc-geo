"""model/coords.py: printed locations to latitude/longitude, never guessing silently."""

import pytest

from extract import patterns
from model import coords, gisio

LAT, LON = 32.776389, -79.931111  # 32°46'35" N, 79°55'52" W (Charleston peninsula)


def close(r, lat, lon, tol=1e-5):
    assert r is not None
    assert r["lat"] == pytest.approx(lat, abs=tol) and r["lon"] == pytest.approx(lon, abs=tol)


# --- decimal degrees ---------------------------------------------------------

@pytest.mark.parametrize("text", [
    "32.776389, -79.931111",
    "32.776389 N, 79.931111 W",
    "32.776389°N 79.931111°W",
    "lat. 32.776389, long. -79.931111",
    "-79.931111, 32.776389",           # longitude first: told apart by magnitude and sign
])
def test_decimal_degrees(text):
    r = coords.parse(text)
    close(r, LAT, LON)
    assert r["format"] == "decimal" and not any("west" in a for a in r["assumptions"])


def test_decimal_without_west_sign_is_assumed_and_says_so():
    r = coords.parse("Latitude 32.776389, Longitude 79.931111")
    close(r, LAT, LON)
    assert any("west" in a for a in r["assumptions"])


def test_decimal_ignores_lengths_next_to_coordinates():
    close(coords.parse("lat 32.776389, long -79.931111, elev. 12.5 ft"), LAT, LON)


# --- degrees, minutes, seconds -----------------------------------------------

@pytest.mark.parametrize("text", [
    "lat 32°46'35\" N, long 79°55'52\" W",
    "32° 46′ 35″ N., 79° 55′ 52″ W.",
    "N32°46'35\" W79°55'52\"",
    "Lat. 32°46'35\", Long. 79°55'52\" W",
    "32 46 35 N, 79 55 52 W",
    "32-46-35N 79-55-52W",
    "lat 32:46:35, long 79:55:52 W",
    "Lat. 32 deg 46 min 35 sec N, Long. 79 deg 55 min 52 sec W",
])
def test_dms(text):
    r = coords.parse(text)
    close(r, LAT, LON)
    assert r["format"] == "dms"


def test_dms_decimal_minutes():
    close(coords.parse("N 32°46.5833' W 79°55.8667'"), 32 + 46.5833 / 60, -(79 + 55.8667 / 60))


def test_dms_without_hemisphere_assumes_west_and_flags_it():
    r = coords.parse("latitude 33°20'41\", longitude 81°52'10\"")
    close(r, 33 + 20 / 60 + 41 / 3600, -(81 + 52 / 60 + 10 / 3600))
    assert any("west" in a for a in r["assumptions"])


# --- USGS packed DDMMSS / DDDMMSS ----------------------------------------------

@pytest.mark.parametrize("text", [
    "lat 332041, long 0815210",
    "Lat 332041 Long 0815210",
    "332041 0815210",
    "LAT: 332041N LONG: 0815210W",
    "latitude 332041, longitude 815210",
])
def test_packed_usgs(text):
    r = coords.parse(text)
    close(r, 33 + 20 / 60 + 41 / 3600, -(81 + 52 / 60 + 10 / 3600))
    assert r["format"] == "packed_dms"


def test_packed_decimal_seconds():
    close(coords.parse("lat 332041.5, long 0815210.25"), 33 + 20 / 60 + 41.5 / 3600, -(81 + 52 / 60 + 10.25 / 3600))


def test_packed_needs_labels_or_the_seven_digit_longitude():
    assert coords.parse("332041 815210") is None   # two six-digit numbers: could be anything


# --- SC State Plane ------------------------------------------------------------

def test_state_plane_nad83_feet_round_trip():
    e, n = coords.latlon_to_state_plane(LAT, LON, unit="ft")
    r = coords.parse(f"SC State Plane NAD83: N {n:,.2f} ft, E {e:,.2f} ft")
    close(r, LAT, LON, 1e-7)
    assert r["format"] == "state_plane" and r["datum"] == "NAD83" and r["approximate"] is False
    assert r["assumptions"] == []


def test_state_plane_origin_is_the_projection_origin():
    # FIPS 3900: latitude of origin 31°50' N, central meridian 81° W, false easting 609,600 m = 2,000,000 ft.
    r = coords.parse("NAD 83 State Plane, Easting 2,000,000 ft, Northing 0 ft")
    close(r, 31 + 50 / 60, -81.0, 1e-9)
    assert coords.state_plane_to_latlon(609600.0, 0.0, unit="m") == pytest.approx((31 + 50 / 60, -81.0), abs=1e-9)


def test_state_plane_agrees_with_the_independent_implementation():
    # extract/patterns.py has its own Lambert conic; model/coords.py goes through model/gisio.py.
    for lat, lon in ((32.0333, -80.85), (33.9, -81.03), (34.95, -82.4), (32.78, -79.93)):
        e, n = patterns.sc_state_plane_forward(lat, lon)  # international feet
        assert coords.state_plane_to_latlon(e, n, unit="ft") == pytest.approx((lat, lon), abs=1e-8)
        assert coords.latlon_to_state_plane(lat, lon, unit="ft") == pytest.approx((e, n), abs=1e-3)


@pytest.mark.parametrize("unit,label", [("m", "m"), ("us_ft", "US survey feet")])
def test_state_plane_metres_and_survey_feet(unit, label):
    e, n = coords.latlon_to_state_plane(LAT, LON, unit=unit)
    close(coords.parse(f"NAD83 SC State Plane ({label}) E {e:.3f} N {n:.3f}" if unit == "us_ft"
                       else f"NAD83 E {e:.3f} m N {n:.3f} m"), LAT, LON, 1e-7)


def test_state_plane_unit_from_easting_range_is_flagged():
    e, n = coords.latlon_to_state_plane(LAT, LON, unit="ft")
    r = coords.parse(f"NAD83 state plane x={e:.1f}, y={n:.1f}")
    close(r, LAT, LON, 1e-6)
    assert any("feet" in a for a in r["assumptions"])


def test_state_plane_nad27_south_zone_is_approximate():
    lon0, lat0, lat1, lat2, fe = gisio._FIPS[("3902", "nad27")]
    x, y = gisio.lcc_forward(LON, LAT, lon0, lat0, lat1, lat2, fe, 0.0, *gisio.CLARKE_1866)
    r = coords.parse(f"SC State Plane NAD 27, South Zone: x = {x / gisio.US_FOOT:,.1f} ft, y = {y / gisio.US_FOOT:,.1f} ft")
    want_lon, want_lat = gisio.nad27_to_nad83(LON, LAT)
    close(r, want_lat, want_lon, 1e-6)
    assert r["datum"] == "NAD27" and r["approximate"] is True


@pytest.mark.parametrize("text", [
    "E 2,312,000, N 345,000 (SC State Plane)",            # no datum: NAD27 and NAD83 differ by hundreds of feet
    "NAD27 State Plane x = 2,312,000 ft, y = 345,000 ft",  # NAD27 without its zone
    "NAD83 and NAD27 E 2,312,000 N 345,000",               # two datums
    "NAD83 E 2,312,000 ft N 345,000 m",                    # mixed units
    "NAD83 E 9,312,000 ft N 345,000 ft",                   # far outside South Carolina
])
def test_state_plane_ambiguous_is_none(text):
    assert coords.parse(text) is None


# --- never guess -------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    None, "", "not stated", "0.5 mi north of Ladson", "near the bridge on SC 61",
    "32.5, 33.1",                                   # two latitudes?
    "332041",                                       # one number
    "lat 32°46'35\"",                               # latitude only
    "from 32.70, -79.95 to 32.80, -79.90",          # two places
    "lat 32°75'10\" N, long 79°55'52\" W",          # 75 minutes
    "lat 336041, long 0815210",                     # 60 minutes
    "45.0 N, 100.0 W",                              # not in or near South Carolina
    "Sample 10-12-85, 32 ft",                       # a date and a depth
    "lat 32.776389 N, long 79.931111 N",            # two latitudes by hemisphere
])
def test_ambiguous_or_missing_is_none(text):
    assert coords.parse(text) is None


def test_numbers_pass_through_unparsed():
    assert coords.parse(32.7) is None


def test_geographic_datum_is_reported_and_nad27_shifted():
    r = coords.parse("32.776389, -79.931111 (NAD 83)")
    assert r["datum"] == "NAD83" and r["approximate"] is False and r["assumptions"] == []
    r = coords.parse("32.776389, -79.931111")
    assert r["datum"] is None and "horizontal datum not stated" in r["assumptions"]
    r = coords.parse("lat 32°46'35\" N, long 79°55'52\" W (NAD 27)")
    want_lon, want_lat = gisio.nad27_to_nad83(LON, LAT)
    close(r, want_lat, want_lon, 1e-6)
    assert r["datum"] == "NAD27" and r["approximate"] is True


def test_result_names_the_conversion():
    r = coords.parse("lat 332041, long 0815210")
    assert "packed" in r["conversion"] and r["conversion"].startswith("model.coords")
