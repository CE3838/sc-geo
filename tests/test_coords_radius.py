"""model/coords.py location_radius: how far a converted coordinate may be from the place, from printed precision."""

import pytest

from model import coords


def radius(text, **kw):
    r = coords.location_radius(text, **kw)
    assert r is not None, text
    return r


def test_decimal_degrees_radius_is_half_the_last_printed_place():
    five = radius("32.77639, -79.93111 (NAD 83)")
    assert five["rounding_m"] == pytest.approx(0.73, abs=0.05) and five["datum_m"] == 0
    two = radius("32.78, -79.93 (NAD 83)")
    # half of 0.01 degree: 557 m north-south, 467 m east-west at 32.8 N
    assert two["rounding_m"] == pytest.approx(727, abs=10)
    one = radius("32.8, -79.9 (NAD 83)")
    assert one["radius_m"] > 7000


def test_dms_seconds_minutes_and_degrees():
    sec = radius("32°46'35\" N, 79°55'52\" W, NAD 83")
    assert sec["rounding_m"] == pytest.approx(19.6, abs=1)
    minutes = radius("32°47' N, 79°56' W, NAD 83")
    assert minutes["rounding_m"] == pytest.approx(1210, abs=20)
    assert "minutes" in " ".join(minutes["basis"])


def test_whole_zero_seconds_count_as_minutes():
    r = radius("lat 32°47'00\" N., long 79°53'00\" W. NAD 83")
    assert r["rounding_m"] == pytest.approx(1210, abs=20)


def test_packed_dms_is_one_second():
    r = radius("lat 330112, long 0801005 NAD 83")
    assert r["rounding_m"] == pytest.approx(19.6, abs=1)


def test_printed_approximate_widens_by_one_place():
    plain = radius("lat 32°46'35\" N., long 79°55'52\" W., NAD 83")
    approx = radius("lat 32°46'35\" N., long 79°55'52\" W., NAD 83 (approximate)")
    assert approx["rounding_m"] == pytest.approx(plain["rounding_m"] * 60, rel=0.01)
    assert any("approximate" in b for b in approx["basis"])


def test_unstated_datum_adds_the_nad27_shift():
    r = radius("32.77639, -79.93111")
    assert 15 < r["datum_m"] < 40
    assert r["radius_m"] == round(r["rounding_m"] + r["datum_m"])


def test_printed_nad27_adds_the_shift_accuracy():
    r = radius("32.77639, -79.93111 (NAD 27)")
    assert r["datum_m"] == coords.NAD27_SHIFT_M


def test_state_plane_rounding_and_trailing_zeros():
    r = radius("Northing 405035.719, Easting 2324888.00 (NAD 83, feet)")
    assert r["rounding_m"] < 0.01 and r["datum_m"] == 0
    whole = radius("Northing 405000, Easting 2325000 (NAD 83, feet)")
    # trailing zeros: rounded to 1,000 ft -> half is 500 ft each way
    assert whole["rounding_m"] == pytest.approx((500 ** 2 * 2) ** 0.5 * 0.3048, rel=0.01)


def test_assumed_state_plane_datum_adds_the_nad27_alternative_inside_the_bbox():
    text = "Northing 397987.2661, Easting 2320919.034"
    assert coords.location_radius(text) is None          # not readable without the assumption
    r = radius(text, assume_state_plane_nad83=True, bbox=[-80.2, 32.6, -79.7, 33.1])
    # the NAD27 south-zone reading of the same numbers is about 39 m away; the north-zone one is far outside
    assert 30 < r["datum_m"] < 50
    far = radius(text, assume_state_plane_nad83=True, bbox=None)
    assert far["datum_m"] > 100_000                      # without a bbox the north-zone reading counts too


def test_unreadable_text_has_no_radius():
    assert coords.location_radius("near Givhans") is None
    assert coords.location_radius(None) is None
