"""Known wells, borings, cores, test holes and springs for the map, and water and rock tests per site (merge/wells.py)."""

import copy
import json

import pytest

from merge import site_tests, wells
from tests.test_merge_site_tests import COORD, DOC, SID, sv

BBOX = [-80.4, 32.8, -79.9, 33.2]
CATALOG = {SID: {"id": SID, "bbox": BBOX, "citation": DOC["citation"], "title": DOC["title"], "year": 1998,
                 "publisher": "U.S. Geological Survey", "ngmdb_url": "https://ngmdb.usgs.gov/Prodesc/proddesc_78.htm"},
           "ngmdb:79": {"id": "ngmdb:79"}}


def derived(lat, lon, page, **kw):
    return {**COORD, "value": {"lat": lat, "lon": lon}, "page": page, "format": "decimal", **kw}


def doc():
    d = copy.deepcopy(DOC)
    d["observations"] += [
        {"kind": "boring", "label": sv("B-7", 3, "Boring B-7"),
         "location": sv("33.05, -80.12 (NAD 83)", 3, "33.05, -80.12",
                        derived_coordinates=derived(33.05, -80.12, 3, datum="NAD83", approximate=False)),
         "total_depth": sv("61 ft", 3, "total depth 61 ft", normalized={"min_ft": 61.0, "max_ft": 61.0})},
        {"kind": "well", "label": sv("DOR-5", 3, "Well DOR-5"),
         "location": sv("33.1, -80.2", 3, "33.1, -80.2", derived_coordinates=derived(33.1, -80.2, 3))},
        {"kind": "auger_hole", "label": sv("AH-1", 3, "Auger hole AH-1"),
         "location": sv("near the river", 3, "near the river")},
        {"kind": "outcrop", "label": sv("OC-1", 3, "Outcrop OC-1"),
         "location": sv("33.0512, -80.1201 (NAD 83)", 3, "33.0512, -80.1201",
                        derived_coordinates=derived(33.0512, -80.1201, 3, datum="NAD83"))},
    ]
    d["observations"][0]["elevation"]["navd88"] = {
        "value": {"min_ft": 42.9, "max_ft": 42.9}, "source_id": SID, "page": 1, "extraction_method": "datum_conversion",
        "confidence": 0.6, "inferred": True, "locator": None, "conversion": "VERTCON"}
    d["water_test_tables"] = [{
        "compact": True, "source_id": SID, "extraction_method": "llm", "kind": "well",
        "source_table": sv("Table 9", 5, "Table 9"),
        "units": sv("milligrams per liter", 5, "milligrams per liter"),
        "columns": [{"field": "observation", "header": sv("Well", 5, "Well")},
                    {"field": "value", "parameter": sv("Sulfate", 5, "Sulfate",
                                                        normalized={"name": "sulfate", "category": "major_ion",
                                                                    "inferred": True})}],
        "row_fields": ["page", "quote", "quote_match", "text_method", "confidence", "cells"],
        "rows": [[5, "DOR-120  3.1", "exact", "pdf_text", 0.8, ["DOR-120", "3.1"]]],
    }]
    return d


@pytest.fixture
def extracted(tmp_path):
    d = tmp_path / "extracted"
    d.mkdir()
    (d / "ngmdb_78.json").write_text(json.dumps(doc()))
    return d


@pytest.fixture
def out(extracted):
    return wells.build(extracted, CATALOG)


def feats(out):
    return {f["properties"]["l"]: f for f in out["wells"]["features"]}


def test_every_well_kind_with_a_location_is_a_point(out):
    f = feats(out)
    assert set(f) == {"DOR-120", "B-7"}          # DOR-5: radius > 1 mile; AH-1, DOR-SP1, CH-2: no location
    assert "OC-1" not in f                       # outcrops are not wells
    assert out["wells"]["type"] == "FeatureCollection"
    b7 = f["B-7"]
    assert b7["geometry"] == {"type": "Point", "coordinates": [-80.12, 33.05]}
    p = b7["properties"]
    assert p["k"] == "boring" and p["s"] == SID and p["p"] == 3 and p["q"] == "33.05, -80.12"
    assert p["ci"] == 1 and p["r"] == pytest.approx(727, abs=10) and p["r"] <= wells.MAX_LOCATION_RADIUS_M
    assert p["td"] == {"v": "61 ft", "ft": 61.0, "p": 3, "q": "total depth 61 ft", "c": 0.8, "i": 0,
                       "m": "llm", "lc": None}
    assert p["wt"] == 0 and p["rt"] == 0


def test_well_with_tests_has_counts_elevation_and_navd88(out):
    p = feats(out)["DOR-120"]["properties"]
    assert p["id"] == f"{SID}#DOR120"
    assert p["wt"] == 3                           # two water_tests + one compact table cell
    assert p["el"]["ft"] == 42.0 and p["el"]["d"] == "NGVD29" and p["el"]["p"] == 1
    assert p["el"]["n88"] == {"ft": 42.9, "c": 0.6, "i": 1, "m": "datum_conversion", "cv": "VERTCON", "p": 1}
    assert p["r"] < 100                           # packed DMS to the second, datum not printed


def test_coordinates_are_rounded_and_keys_are_documented(out):
    for f in out["wells"]["features"]:
        for x in f["geometry"]["coordinates"]:
            assert round(x, 6) == x
    keys = out["wells"]["keys"]
    for f in out["wells"]["features"]:
        assert set(f["properties"]) <= set(keys)
    assert "without warranty" in out["wells"]["notes"]


def test_drop_counts_by_reason_and_kind(out):
    s = out["wells"]["counts"]
    assert s["kept"] == {"well": 1, "boring": 1}
    assert s["no_location"] == {"auger_hole": 1, "spring": 1, "core": 1}
    assert s["radius_over_limit"] == {"well": 1}


def test_water_tests_on_their_own_keyed_by_site(out):
    w = out["water"]
    assert w["format"] == "sc-geo water tests" and "without warranty" in w["notes"]
    site = w["sites"][f"{SID}#DOR120"]
    rows = [dict(zip(w["columns"], r)) for r in site["rows"]]
    assert len(rows) == 3
    ph = rows[0]
    assert ph["parameter"] == "pH" and ph["value"] == 5.4 and ph["units"] == "standard units"
    assert ph["page"] == 1 and ph["quote"] == "5.4" and ph["inferred"] == 0 and ph["top_ft"] == 15.0
    so4 = rows[2]
    assert so4["parameter"] == "Sulfate" and so4["units"] == "milligrams per liter"
    assert so4["locator"] == "water_test_tables[0] row 1 column 2" and so4["page"] == 5
    # sites dropped from the map are not in the map files
    assert set(w["sites"]) == {f"{SID}#DOR120"}
    assert out["rock"]["sites"] == {}             # CH-2 has no location
    assert SID in w["sources"] and "url" in w["sources"][SID]


def test_site_tests_export_includes_compact_tables(extracted):
    full = site_tests.build(extracted, catalog=CATALOG)
    well = next(s for s in full["sites"] if s["label"] == "DOR-120")
    assert len(well["water_tests"]) == 3


def test_cli_writes_three_files(extracted, tmp_path):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps(list(CATALOG.values())))
    dest = tmp_path / "sites"
    assert wells.main(["--extracted", str(extracted), "--catalog", str(cat), "--out-dir", str(dest)]) == 0
    assert {p.name for p in dest.iterdir()} == {"wells.geojson", "water-tests.json", "rock-tests.json"}
    assert json.loads((dest / "wells.geojson").read_text())["counts"]["kept"]["well"] == 1


def test_real_extracted_data_builds():
    out = wells.build()
    assert all(f["properties"]["r"] is None or f["properties"]["r"] <= wells.MAX_LOCATION_RADIUS_M
               for f in out["wells"]["features"])
