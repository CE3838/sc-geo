"""Export of water tests and rock tests per site (merge/site_tests.py)."""

import json

import pytest

from merge import site_tests

SID = "ngmdb:78"


def sv(value, page, quote, inferred=False, conf=0.8, **extra):
    return {"value": value, "source_id": SID, "page": page, "extraction_method": "llm", "confidence": conf,
            "inferred": inferred, "locator": None, "quote": quote, "quote_match": "exact",
            "text_method": "pdf_text", "verification": None, **extra}


COORD = {"value": {"lat": 33.02, "lon": -80.168}, "source_id": SID, "page": 1, "extraction_method": "inference",
         "confidence": 0.64, "inferred": True, "locator": None, "format": "packed_dms", "datum": None,
         "approximate": True, "assumptions": ["western longitude"], "conversion": "model.coords packed DMS"}

DOC = {
    "source_id": SID, "title": "Ground-water quality near Summerville", "citation": "Doe, J., 1998, Ground-water "
    "quality near Summerville: USGS WRIR 98-1.", "year": 1998, "publisher": "U.S. Geological Survey",
    "observations": [{
        "kind": "well",
        "label": sv("DOR-120", 1, "DOR-120"),
        "location": sv("lat 330112, long 0801005", 1, "330112 0801005", derived_coordinates=COORD),
        "elevation": sv(42, 1, "42", units="ft", normalized={"min_ft": 42.0, "max_ft": 42.0}),
        "datum": sv("NGVD 29", 1, "NGVD 29", normalized="NGVD29"),
        "depth_reference": sv("land surface", 1, "below land surface"),
    }],
    "water_tests": [{
        "kind": "well",
        "observation": sv("DOR 120", 1, "DOR-120"),
        "date": sv("6/10/1997", 1, "6/10/1997", normalized="1997-06-10"),
        "top": sv("15 ft", 1, "15-25", normalized={"min_ft": 15.0, "max_ft": 15.0}),
        "bottom": sv("25 ft", 1, "15-25", normalized={"min_ft": 25.0, "max_ft": 25.0}),
        "parameter": sv("pH", 1, "pH", normalized={"name": "pH", "category": "field", "inferred": True}),
        "value": sv(5.4, 1, "5.4", normalized={"number": 5.4, "qualifier": None}),
        "units": sv("standard units", 1, "(standard units)"),
    }, {
        "kind": "well",
        "observation": sv("DOR-120", 2, "DOR-120"),
        "parameter": sv("Chloride", 2, "Chloride", normalized={"name": "chloride", "category": "major_ion",
                                                              "inferred": True}),
        "value": sv("<0.5", 2, "<0.5", normalized={"number": 0.5, "qualifier": "<"}),
        "units": sv("milligrams per liter", 2, "milligrams per liter"),
    }, {
        "kind": "spring",
        "observation": sv("DOR-SP1", 2, "Spring DOR-SP1"),
        "location": sv("at Givhans", 2, "at Givhans"),
        "parameter": sv("chloride", 2, "chloride 8.1"),
        "value": sv(8.1, 2, "chloride 8.1"),
    }],
    "rock_tests": [{
        "kind": "core",
        "observation": sv("CH-2", 4, "core hole CH-2"),
        "location": sv("Dorchester County", 4, "Dorchester County"),
        "sample_id": sv("R-1", 4, "R-1"),
        "top": sv("102.0 ft", 4, "102.0-102.6", normalized={"min_ft": 102.0, "max_ft": 102.0}),
        "bottom": sv("102.6 ft", 4, "102.0-102.6", normalized={"min_ft": 102.6, "max_ft": 102.6}),
        "depth_reference": sv("land surface", 4, "Depths in feet below land surface"),
        "test_type": sv("UCS", 4, "UCS (psi)", normalized={"type": "ucs", "inferred": True}),
        "value": sv(1250, 4, "1,250", normalized={"number": 1250.0, "qualifier": None}),
        "units": sv("psi", 4, "UCS (psi)"),
        "standard": sv("ASTM D7012 method C", 4, "ASTM D7012 method C"),
    }],
}


@pytest.fixture
def extracted(tmp_path):
    d = tmp_path / "extracted"
    d.mkdir()
    (d / "ngmdb_78.json").write_text(json.dumps(DOC))
    (d / "ngmdb_79.json").write_text(json.dumps({"source_id": "ngmdb:79", "units": [], "observations": []}))
    return d


def build(extracted, catalog=None):
    return site_tests.build(extracted, catalog={SID: {"id": SID}, "ngmdb:79": {"id": "ngmdb:79"}}
                            if catalog is None else catalog)


def test_sites_group_tests_by_source_and_label(extracted):
    out = build(extracted)
    assert out["format"] == "sc-geo site tests" and out["version"] == 1
    sites = {(s["source_id"], s["label"]): s for s in out["sites"]}
    assert set(sites) == {(SID, "DOR-120"), (SID, "DOR-SP1"), (SID, "CH-2")}
    well = sites[(SID, "DOR-120")]
    assert well["kind"] == "well" and len(well["water_tests"]) == 2 and well["rock_tests"] == []
    assert well["site_key"] == "DOR120"            # "DOR 120" and "DOR-120" are the same label
    core = sites[(SID, "CH-2")]
    assert core["kind"] == "core" and len(core["rock_tests"]) == 1


def test_site_location_comes_from_the_linked_observation_and_is_flagged_inferred(extracted):
    well = next(s for s in build(extracted)["sites"] if s["label"] == "DOR-120")
    loc = well["location"]
    assert loc["lat"] == 33.02 and loc["lon"] == -80.168 and loc["inferred"] is True
    assert loc["from"] == "observation" and loc["page"] == 1 and loc["approximate"] is True
    assert loc["as_printed"] == "lat 330112, long 0801005"
    assert well["elevation"]["ft"] == 42.0 and well["elevation"]["datum"] == "NGVD29"
    assert well["elevation"]["page"] == 1


def test_unplaced_sites_keep_the_printed_location_and_no_coordinates(extracted):
    spring = next(s for s in build(extracted)["sites"] if s["label"] == "DOR-SP1")
    assert spring["kind"] == "spring"
    assert spring["location"] == {"lat": None, "lon": None, "as_printed": "at Givhans", "from": "test", "page": 2,
                                  "inferred": False}


def test_each_test_has_depths_values_and_full_citations(extracted):
    out = build(extracted)
    well = next(s for s in out["sites"] if s["label"] == "DOR-120")
    ph, cl = well["water_tests"]
    assert ph["parameter"] == {"as_printed": "pH", "name": "pH", "category": "field", "inferred": True}
    assert ph["value"] == {"as_printed": 5.4, "number": 5.4, "qualifier": None, "units": "standard units"}
    assert ph["depth"] == {"top_ft": 15.0, "bottom_ft": 25.0, "reference": "land surface"}
    assert ph["date"] == "1997-06-10"
    assert ph["fields"]["value"] == {"value": 5.4, "page": 1, "quote": "5.4", "confidence": 0.8,
                                     "inferred": False, "verification": None, "locator": None}
    assert ph["source_id"] == SID and ph["pages"] == [1]
    assert cl["value"]["qualifier"] == "<" and cl["value"]["number"] == 0.5
    assert cl["depth"] is None
    assert out["sources"][SID]["citation"].startswith("Doe, J., 1998")
    rock = next(s for s in out["sites"] if s["label"] == "CH-2")["rock_tests"][0]
    assert rock["test_type"] == {"as_printed": "UCS", "type": "ucs", "inferred": True}
    assert rock["value"]["units"] == "psi" and rock["depth"]["top_ft"] == 102.0
    assert rock["fields"]["standard"]["value"] == "ASTM D7012 method C"


def test_missing_units_stay_missing(extracted):
    spring = next(s for s in build(extracted)["sites"] if s["label"] == "DOR-SP1")
    assert spring["water_tests"][0]["value"]["units"] is None


def test_counts_and_terms(extracted):
    out = build(extracted)
    assert out["counts"] == {"sites": 3, "water_tests": 3, "rock_tests": 1, "sources": 1}
    assert "without warranty" in out["notes"] and "public" in out["notes"].lower()


def test_only_catalog_records_are_exported(extracted):
    out = build(extracted, catalog={"ngmdb:79": {"id": "ngmdb:79"}})
    assert out["sites"] == [] and out["sources"] == {}


def test_write_and_cli(extracted, tmp_path):
    dest = tmp_path / "web" / "data" / "sites" / "site-tests.json"
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps([{"id": SID}]))
    assert site_tests.main(["--extracted", str(extracted), "--out", str(dest), "--catalog", str(cat)]) == 0
    written = json.loads(dest.read_text())
    assert written["counts"]["sites"] == 3


def test_real_extracted_data_exports():
    out = site_tests.build()
    assert out["counts"]["sites"] == len(out["sites"])
