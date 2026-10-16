"""Normalizers for water tests and rock tests (extract/labtests.py)."""

import pytest

from extract import labtests as lt


# --- water-test parameter names ------------------------------------------------

@pytest.mark.parametrize("printed,name,category", [
    ("pH, field (standard units)", "pH", "field"),
    ("Specific conductance (µS/cm at 25 °C)", "specific conductance", "field"),
    ("Water temperature (°C)", "temperature", "field"),
    ("Dissolved oxygen", "dissolved oxygen", "field"),
    ("Depth to water at sampling", "water level", "field"),
    ("Calcium, dissolved (mg/L as Ca)", "calcium", "major_ion"),
    ("Chloride, dissolved (mg/L as Cl)", "chloride", "major_ion"),
    ("Bicarbonate (as CaCO3)", "bicarbonate", "major_ion"),
    ("Mg", "magnesium", "major_ion"),
    ("Nitrite plus nitrate, dissolved (mg/L as N)", "nitrate plus nitrite", "nutrient"),
    ("Nitrate", "nitrate", "nutrient"),
    ("Orthophosphate", "orthophosphate", "nutrient"),
    ("Iron, dissolved (Fe)", "iron", "metal_trace"),
    ("Ferrous iron", "ferrous iron", "metal_trace"),
    ("Arsenic", "arsenic", "metal_trace"),
    ("Benzene", "benzene", "organic"),
    ("Methyl tert-butyl ether (MTBE)", "MTBE", "organic"),
    ("Trichloroethene", "trichloroethene", "organic"),
    ("Ethylene dibromide (EDB)", "ethylene dibromide", "organic"),
    ("Atrazine", "atrazine", "pesticide"),
    ("Deethylatrazine", "deethylatrazine", "pesticide"),
    ("Tritium (pCi/L)", "tritium", "isotope_age"),
    ("CFC-12 apparent age", "CFC-12", "isotope_age"),
    ("Radium-226", "radium-226", "isotope_age"),
    ("Transmissivity", "transmissivity", "hydraulic"),
    ("Horizontal hydraulic conductivity (ft/d)", "hydraulic conductivity", "hydraulic"),
    ("Storage coefficient", "storativity", "hydraulic"),
    ("Specific capacity, in gallons per minute per foot", "specific capacity", "hydraulic"),
])
def test_water_parameter_names(printed, name, category):
    n = lt.water_parameter(printed)
    assert n == {"name": name, "category": category, "inferred": True}


@pytest.mark.parametrize("printed", [
    "Calcium and magnesium",          # two parameters
    "Ca/Mg ratio",
    "Constituent",                    # no parameter
    "DO",                             # too short to be sure
    "",
])
def test_water_parameter_left_alone_when_ambiguous(printed):
    assert lt.water_parameter(printed) is None


# --- rock-test types -------------------------------------------------------------

@pytest.mark.parametrize("printed,kind", [
    ("Unconfined compressive strength", "ucs"),
    ("Uniaxial compressive strength (ASTM D7012, method C)", "ucs"),
    ("UCS", "ucs"),
    ("ASTM D2938", "ucs"),
    ("Point load index Is(50)", "point_load"),
    ("ASTM D5731", "point_load"),
    ("Splitting tensile strength (Brazilian)", "brazilian_tensile"),
    ("ASTM D3967", "brazilian_tensile"),
    ("Triaxial compressive strength (ASTM D7012)", "triaxial"),
    ("Slake durability index, second cycle", "slake_durability"),
    ("RQD", "rqd"),
    ("Rock quality designation", "rqd"),
    ("Core recovery", "core_recovery"),
    ("Unit weight", "unit_weight"),
    ("Dry density", "density"),
    ("Absorption", "absorption"),
    ("Young's modulus", "elastic_modulus"),
    ("Poisson's ratio", "poisson_ratio"),
    ("Specific gravity", "specific_gravity"),
])
def test_rock_test_types(printed, kind):
    assert lt.rock_test_type(printed) == {"type": kind, "inferred": True}


@pytest.mark.parametrize("printed", ["ASTM D7012", "Young's modulus and Poisson's ratio", "Lab test", None])
def test_rock_test_type_left_alone_when_ambiguous(printed):
    assert lt.rock_test_type(printed) is None


# --- values and qualifiers ---------------------------------------------------------

@pytest.mark.parametrize("printed,expected", [
    (7.2, {"number": 7.2, "qualifier": None}),
    ("7.2", {"number": 7.2, "qualifier": None}),
    ("<0.5", {"number": 0.5, "qualifier": "<"}),
    ("< 0.5 mg/L", {"number": 0.5, "qualifier": "<"}),
    ("less than 1", {"number": 1.0, "qualifier": "<"}),
    (">2,000", {"number": 2000.0, "qualifier": ">"}),
    ("ND", {"number": None, "qualifier": "ND"}),
    ("not detected", {"number": None, "qualifier": "ND"}),
    ("E0.02", {"number": 0.02, "qualifier": "E"}),
    ("1.2E-04", {"number": 1.2e-4, "qualifier": None}),
    ("2.0x10-9", {"number": 2.0e-9, "qualifier": None}),
    ("3 × 10^5 ft2/d", {"number": 3e5, "qualifier": None}),
    ("0.09 to 0.21", {"min": 0.09, "max": 0.21, "qualifier": None}),
    ("-0.5", {"number": -0.5, "qualifier": None}),
])
def test_test_values(printed, expected):
    assert lt.parse_value(printed) == expected


@pytest.mark.parametrize("printed", ["--", "trace", "", None, "see note"])
def test_unparsed_values(printed):
    assert lt.parse_value(printed) is None


@pytest.mark.parametrize("printed,q", [("<", "<"), ("less than", "<"), (">", ">"), ("ND", "ND"),
                                        ("nd", "ND"), ("Not detected", "ND"), ("BDL", "ND"), ("E", "E"),
                                        ("estimated", "E"), ("J", None)])
def test_qualifiers(printed, q):
    assert lt.qualifier(printed) == q


@pytest.mark.parametrize("value,has", [
    ("0.5 mg/L", True), ("95%", True), ("1,250 psi", True), ("12 ft/d", True), ("25 °C", True),
    ("<0.5 µg/L", True), (7.2, False), ("7.2", False), ("1.2E-04", False), ("ND", False), ("<0.5", False),
    ("2.0x10-9", False),
])
def test_value_carries_units(value, has):
    assert lt.value_has_units(value) is has


# --- the "|" for a digit OCR misread ------------------------------------------------

@pytest.mark.parametrize("quote,flag", [
    ("| to 6 feet", True), ("0.|2 mg/L", True), ("|2.5", True), ("12|", True), ("| - 4 ft", True), ("12 | 14", False),
    ("Well | Depth | Value", False), ("12 to 16 feet", False), ("pH 7.2", False),
])
def test_pipe_digit(quote, flag):
    assert lt.pipe_digit(quote) is flag
