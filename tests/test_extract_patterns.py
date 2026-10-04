import math

import pytest

from extract import patterns as p
from model.units import Lexicon


# --- Munsell -----------------------------------------------------------------

@pytest.mark.parametrize("text,hue,value,chroma", [
    ("2.5Y 4/3", "2.5Y", 4, 3),
    ("olive brown (2.5Y 4/3)", "2.5Y", 4, 3),
    ("10YR5/6", "10YR", 5, 6),
    ("10 YR 6/3", "10YR", 6, 3),
    ("5GY 4/1", "5GY", 4, 1),
    ("N 2.5/", "N", 2.5, 0),
    ("7.5yr 3/2", "7.5YR", 3, 2),
])
def test_munsell(text, hue, value, chroma):
    m = p.munsell(text)
    assert (m["hue"], m["value"], m["chroma"]) == (hue, value, chroma)
    assert m["notation"].startswith(hue)


def test_munsell_rejects_non_colors():
    assert p.munsell("gray sand") is None
    assert p.munsell("12 ft") is None


# --- lengths -----------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("12 ft", (12.0, 12.0)),
    ("12 feet", (12.0, 12.0)),
    ("3.5 m", (3.5 / 0.3048, 3.5 / 0.3048)),
    ("10-15 feet", (10.0, 15.0)),
    ("10 to 15 ft thick", (10.0, 15.0)),
    ("about 1,200 ft", (1200.0, 1200.0)),
    ("6 in.", (0.5, 0.5)),
    ("40 cm", (40 / 30.48, 40 / 30.48)),
    ("5' 6\"", (5.5, 5.5)),
    ("12'", (12.0, 12.0)),
    ("2 to 4 meters", (2 / 0.3048, 4 / 0.3048)),
    ("as much as 30 ft", (None, 30.0)),
    ("more than 100 feet", (100.0, None)),
])
def test_length_ft(text, expected):
    r = p.length_ft(text)
    got = (r["min_ft"], r["max_ft"])
    for a, b in zip(got, expected):
        assert (a is None and b is None) or math.isclose(a, b, rel_tol=1e-6)


def test_length_several_values_give_their_span():
    r = p.length_ft("24 ft thick in the type section; maximum observed thickness of 74 ft")
    assert (r["min_ft"], r["max_ft"]) == (24.0, 74.0)
    assert r["values_ft"] == [24.0, 74.0]
    r = p.length_ft("0.5 m to 2 ft")
    assert r["min_ft"] == pytest.approx(0.5 / 0.3048) and r["max_ft"] == 2.0


def test_length_needs_unit_or_default():
    assert p.length_ft("12") is None
    assert p.length_ft("12", default_unit="m")["max_ft"] == pytest.approx(12 / 0.3048)
    assert p.length_ft(7.5, default_unit="ft")["min_ft"] == 7.5
    assert p.length_ft("not stated") is None


# --- USCS / SPT --------------------------------------------------------------

def test_uscs():
    assert p.uscs("SM") == ["SM"]
    assert p.uscs("SP-SM") == ["SP", "SM"]
    assert p.uscs("CL-ML") == ["CL", "ML"]
    assert p.uscs("(CH)") == ["CH"]
    assert p.uscs("sandy silt") == []
    assert p.uscs("SX") == []


@pytest.mark.parametrize("text,n,refusal", [
    ("N = 23", 23, False),
    ("23", 23, False),
    ("12 bpf", 12, False),
    ("4-6-9", 15, False),
    ("50/2\"", 50, True),
    ("WOH", 0, False),
    ("refusal", None, True),
])
def test_spt(text, n, refusal):
    r = p.spt_n(text)
    assert r["n"] == n and r["refusal"] is refusal


# --- strike and dip ----------------------------------------------------------

def test_strike_dip_quadrant():
    r = p.strike_dip("N45E, 30SE")
    assert (r["strike"], r["dip"], r["dip_direction"]) == (45, 30, "SE")
    r = p.strike_dip("N 30° W, 60° NE")
    assert (r["strike"], r["dip"], r["dip_direction"]) == (330, 60, "NE")


def test_strike_dip_azimuth_assumes_right_hand_rule():
    r = p.strike_dip("045/30")
    assert (r["strike"], r["dip"]) == (45, 30)
    assert r["convention_inferred"] is True


def test_strike_dip_rejects_garbage():
    assert p.strike_dip("steep") is None


# --- coordinates -------------------------------------------------------------

def test_decimal_coordinates():
    r = p.coordinates("32.7765, -79.9311")
    assert r["lat"] == pytest.approx(32.7765) and r["lon"] == pytest.approx(-79.9311)
    r = p.coordinates("32.7765 N, 79.9311 W")
    assert r["lon"] == pytest.approx(-79.9311)


def test_dms_coordinates():
    r = p.coordinates("lat 32°46'35\" N, long 79°55'52\" W")
    assert r["lat"] == pytest.approx(32 + 46 / 60 + 35 / 3600)
    assert r["lon"] == pytest.approx(-(79 + 55 / 60 + 52 / 3600))
    assert r["format"] == "dms"
    r = p.coordinates("32 46 35 N 79 55 52 W")
    assert r["lat"] == pytest.approx(32.776389, abs=1e-5)


def test_west_longitude_sign_assumed_in_sc():
    r = p.coordinates("32.5, 80.1")
    assert r["lon"] == pytest.approx(-80.1)
    assert r["hemisphere_inferred"] is True


def test_state_plane_origin_and_known_point():
    origin = p.coordinates("E 2,000,000 ft, N 0 ft (SC State Plane)")
    assert origin["lat"] == pytest.approx(31.8333333, abs=1e-6)
    assert origin["lon"] == pytest.approx(-81.0, abs=1e-6)
    assert origin["format"] == "sc_state_plane"
    # Round trip through the forward projection.
    e, n = p.sc_state_plane_forward(32.7765, -79.9311)
    back = p.sc_state_plane_inverse(e, n)
    assert back[0] == pytest.approx(32.7765, abs=1e-8) and back[1] == pytest.approx(-79.9311, abs=1e-8)
    # Charleston is roughly 2.32M ft east, 0.37M ft north.
    assert 2.25e6 < e < 2.4e6 and 3.3e5 < n < 4.2e5


def test_coordinates_none():
    assert p.coordinates("near the bridge") is None


# --- ages and names ----------------------------------------------------------

def test_age_ma_is_inferred():
    r = p.age_ma("late Pleistocene")
    assert r == {"younger_ma": 0.0117, "older_ma": 0.129, "inferred": True,
                 "source": "International Chronostratigraphic Chart v2023/09"}
    assert p.age_ma("unknown") is None


def test_unit_name_canonical():
    lex = Lexicon([{"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"}])
    r = p.unit_name("Wando Fm.", lex)
    assert r == {"canonical": "Wando", "in_geolex": True, "inferred": True}
    r = p.unit_name("Ten Mile Hill beds", lex)
    assert r["canonical"] == "ten mile hill" and r["in_geolex"] is False
    assert p.unit_name("undifferentiated sediments", lex) is None


# --- numbers and dates -------------------------------------------------------

def test_number():
    assert p.number("PI = 23") == 23.0
    assert p.number("LL 45%") == 45.0
    assert p.number("moisture 23.5 %") == 23.5
    assert p.number("NP") is None


def test_date():
    assert p.date("6/12/1985") == "1985-06-12"
    assert p.date("June 12, 1985") == "1985-06-12"
    assert p.date("1985-06-12") == "1985-06-12"
    assert p.date("Sept. 1985") == "1985-09"
    assert p.date("spring") is None


def test_length_unit_with_a_qualifier_is_read():
    # Reports often qualify the unit ("feet bls", "ft below land surface"); the unit still counts.
    assert p.length_ft(35, default_unit="feet bls")["max_ft"] == 35
    assert p.length_ft("12", default_unit="ft below land surface")["min_ft"] == 12
    assert p.length_ft(2, default_unit="m bgs")["max_ft"] == pytest.approx(2 / 0.3048)


def test_unknown_length_unit_is_not_normalized_instead_of_crashing():
    assert p.length_ft(3, default_unit="fathoms") is None
    assert p.length_ft("3", default_unit="furlongs") is None
