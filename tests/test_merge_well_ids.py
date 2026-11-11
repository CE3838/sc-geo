"""Placing water-test sites by an exact well ID match to coordinates printed elsewhere (merge/well_ids.py, merge/wells.py).

All fixtures are written for these tests; none is copied from a document.
"""

import json

import pytest

from merge import well_ids, wells

TESTS_SID = "ngmdb:901"     # a water-chemistry report: well IDs, no coordinates
TABLE_SID = "ngmdb:902"     # another report with a well table that prints coordinates
OTHER_SID = "ngmdb:903"     # a third report that disagrees on one well
BBOX = [-80.4, 32.6, -79.6, 33.2]
CATALOG = {s: {"id": s, "bbox": BBOX, "citation": f"Test report {s[-3:]}", "title": f"Report {s[-3:]}",
               "year": 2001} for s in (TESTS_SID, TABLE_SID, OTHER_SID)}


def sv(sid, value, page, quote, **extra):
    return {"value": value, "source_id": sid, "page": page, "extraction_method": "llm", "confidence": 0.8,
            "inferred": False, "locator": None, "quote": quote, **extra}


def coord(sid, lat, lon, page):
    return {"value": {"lat": lat, "lon": lon}, "source_id": sid, "page": page, "extraction_method": "inference",
            "confidence": 0.7, "inferred": True, "locator": None, "format": "decimal", "datum": "NAD83",
            "approximate": False, "assumptions": [], "conversion": "model.coords decimal degrees"}


def located(sid, label, lat, lon, page, kind="well"):
    text = f"{lat:.4f}, {lon:.4f} (NAD 83)"
    return {"kind": kind, "label": sv(sid, label, page, f"Well {label}"),
            "location": sv(sid, text, page, f"{lat:.4f} {lon:.4f}", derived_coordinates=coord(sid, lat, lon, page))}


def water_test(sid, label, page, quote, value=7.1):
    return {"kind": "well", "observation": sv(sid, label, page, quote),
            "parameter": sv(sid, "pH", page, "pH", normalized={"name": "pH", "category": "field", "inferred": True}),
            "value": sv(sid, value, page, str(value), normalized={"number": value, "qualifier": None}),
            "units": sv(sid, "standard units", page, "standard units")}


def docs():
    tests_doc = {
        "source_id": TESTS_SID, "title": "Report 901", "citation": "Test report 901",
        "observations": [
            # the same document's location table on another page, with a zero-padded number
            located(TESTS_SID, "DOR-0007", 32.9011, -80.1022, 30),
        ],
        "water_tests": [
            water_test(TESTS_SID, "CHN–0101", 12, "CHN–0101   7.1"),            # county ID, en dash, zero pad
            water_test(TESTS_SID, "CHN 101", 13, "CHN 101   6.9", 6.9),          # same well, another page
            water_test(TESTS_SID, "Well 3", 12, "Well 3   324455079560001   7.0"),  # USGS number in the row
            water_test(TESTS_SID, "DOR-7", 14, "DOR-7   6.5", 6.5),              # same document, other page
            water_test(TESTS_SID, "GEO-55", 14, "GEO-55   6.0", 6.0),            # coordinates disagree
            water_test(TESTS_SID, "MW-1", 15, "MW-1   5.5", 5.5),                # local name: never matched
            water_test(TESTS_SID, "Johnson farm well", 15, "Johnson farm well   5.8", 5.8),
            water_test(TESTS_SID, "BRK-9", 16, "BRK-9   6.2", 6.2),              # only an imprecise coordinate
        ],
    }
    table_doc = {
        "source_id": TABLE_SID, "title": "Report 902", "citation": "Test report 902",
        "observations": [
            located(TABLE_SID, "CHN-101", 32.7812, -79.9431, 4),
            located(TABLE_SID, "324455079560001", 32.7486, -79.9336, 5),
            located(TABLE_SID, "GEO-55", 33.0011, -80.0022, 5),
            located(TABLE_SID, "MW-1", 32.8, -80.0, 6),
            located(TABLE_SID, "Johnson farm well", 32.81, -80.01, 6),
            {"kind": "well", "label": sv(TABLE_SID, "BRK-9", 7, "Well BRK-9"),
             "location": sv(TABLE_SID, "33.0, -80.0", 7, "33.0 -80.0",
                            derived_coordinates=coord(TABLE_SID, 33.0, -80.0, 7))},
        ],
    }
    other_doc = {
        "source_id": OTHER_SID, "title": "Report 903", "citation": "Test report 903",
        "observations": [located(OTHER_SID, "GEO 0055", 33.0511, -80.0022, 2)],
    }
    return {"ngmdb_901.json": tests_doc, "ngmdb_902.json": table_doc, "ngmdb_903.json": other_doc}


@pytest.fixture
def extracted(tmp_path):
    d = tmp_path / "extracted"
    d.mkdir()
    for name, doc in docs().items():
        (d / name).write_text(json.dumps(doc, ensure_ascii=False))
    return d


@pytest.fixture
def out(extracted):
    return wells.build(extracted, CATALOG)


def placed(out):
    return {f["properties"]["id"]: f for f in out["wells"]["features"] if f["properties"]["s"] == TESTS_SID}


# ---- normalization ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [("CHN-0101", "CHN-101"), ("chn 101", "CHN–101"), ("CHN101", "CHN-101"),
                                 ("ALL383", "ALL-0383"), ("BFT-TF-09", "bft tf 9")])
def test_normalize_case_dashes_spaces_and_zero_padding(a, b):
    assert well_ids.normalize(a) == well_ids.normalize(b)


@pytest.mark.parametrize("a,b", [("CHN-101", "CHN-1010"), ("CHN-101", "CHE-101"), ("CHN-101", "CHN-101A"),
                                 ("CHN-10-1", "CHN-101")])
def test_normalize_keeps_different_ids_apart(a, b):
    assert well_ids.normalize(a) != well_ids.normalize(b)


def test_names_without_a_number_are_not_ids():
    assert well_ids.normalize("Johnson farm well") is None
    assert well_ids.normalize("") is None and well_ids.normalize(None) is None


def test_only_county_well_numbers_and_usgs_site_numbers_match_across_documents():
    assert well_ids.shared_keys({"value": "CHN-0101", "quote": "CHN-0101"}) == {"county:CHN-101"}
    assert well_ids.shared_keys({"value": "MW-1", "quote": "MW-1"}) == set()
    assert well_ids.shared_keys({"value": "BH33", "quote": "BH33"}) == set()
    assert well_ids.shared_keys({"value": "324455079560001", "quote": "x"}) == {"usgs:324455079560001"}
    # a USGS site number printed in the same row as the label is a second ID for it
    assert well_ids.shared_keys({"value": "Well 3", "quote": "Well 3   324455079560001   7.0"}) == {
        "usgs:324455079560001"}
    # two numbers in the row, or a number that is part of a decimal: no USGS ID
    assert well_ids.shared_keys({"value": "Well 3", "quote": "Well 3 324455079560001 324455079560002"}) == set()
    assert well_ids.shared_keys({"value": "W", "quote": "W 0.324455079560001"}) == set()


def test_usgs_numbers_are_never_decoded_into_a_location(out):
    # Well 3's site number encodes about 32.748, -79.933; the point comes only from the printed coordinate
    loc = placed(out)[f"{TESTS_SID}#WELL3"]["properties"]["loc"]
    assert loc == "32.7486, -79.9336 (NAD 83)"


# ---- placement -------------------------------------------------------------------------------------------

def test_county_id_from_another_documents_well_table(out):
    f = placed(out)[f"{TESTS_SID}#CHN0101"]
    p = f["properties"]
    assert f["geometry"]["coordinates"] == [-79.9431, 32.7812]
    assert p["s"] == TESTS_SID and p["ls"] == TABLE_SID
    assert p["ci"] == 1 and p["r"] <= wells.MAX_LOCATION_RADIUS_M
    assert p["p"] == 4 and p["q"] == "32.7812 -79.9431"
    m = p["mt"]
    assert m["note"] == "located by well ID match" and m["i"] == 1 and m["m"] == "inference"
    assert m["test"] == {"s": TESTS_SID, "p": 12, "q": "CHN–0101   7.1"}
    assert m["coord"] == {"s": TABLE_SID, "p": 4, "q": "32.7812 -79.9431", "lc": None, "l": "CHN-101",
                          "lp": 4, "lq": "Well CHN-101"}
    assert "located by well ID match" in p["a"]
    assert TABLE_SID in out["wells"]["sources"]


def test_both_spellings_in_one_document_are_placed(out):
    s = placed(out)
    assert f"{TESTS_SID}#CHN101" in s
    assert s[f"{TESTS_SID}#CHN101"]["properties"]["mt"]["test"]["p"] == 13


def test_usgs_site_number_in_the_test_row(out):
    p = placed(out)[f"{TESTS_SID}#WELL3"]["properties"]
    assert p["ls"] == TABLE_SID and p["mt"]["id"] == "usgs:324455079560001"
    assert placed(out)[f"{TESTS_SID}#WELL3"]["geometry"]["coordinates"] == [-79.9336, 32.7486]


def test_same_documents_location_table_on_another_page(out):
    p = placed(out)[f"{TESTS_SID}#DOR7"]["properties"]
    assert p["ls"] == TESTS_SID and p["p"] == 30 and p["mt"]["test"]["p"] == 14


def test_local_names_and_place_names_are_never_matched(out):
    s = placed(out)
    assert f"{TESTS_SID}#MW1" not in s
    assert f"{TESTS_SID}#JOHNSONFARMWELL" not in s


def test_borrowed_coordinate_keeps_the_one_mile_rule(out):
    assert f"{TESTS_SID}#BRK9" not in placed(out)


def test_conflicting_coordinates_are_not_placed_and_are_listed(out):
    assert f"{TESTS_SID}#GEO55" not in placed(out)
    c = out["conflicts"]
    assert c["count"] == len(c["items"]) == 1
    item = c["items"][0]
    assert item["well_id"] == "county:GEO-55" and item["site"] == f"{TESTS_SID}#GEO55"
    assert item["test"] == {"source_id": TESTS_SID, "page": 14, "quote": "GEO-55   6.0"}
    assert {x["source_id"] for x in item["coordinates"]} == {TABLE_SID, OTHER_SID}
    assert item["max_separation_m"] > wells.MAX_LOCATION_RADIUS_M
    assert out["wells"]["counts"]["id_conflict"] == 1


def test_water_tests_of_matched_sites_are_in_the_tests_file(out):
    w = out["water"]["sites"]
    assert len(w[f"{TESTS_SID}#CHN0101"]["rows"]) == 1
    assert f"{TESTS_SID}#GEO55" not in w and f"{TESTS_SID}#MW1" not in w
    assert out["wells"]["counts"]["id_match"] == 4


def test_match_is_a_stored_value_flagged_inferred(extracted):
    out = wells.build(extracted, CATALOG)
    p = placed(out)[f"{TESTS_SID}#CHN0101"]["properties"]
    from model.provenance import StoredValue
    v = StoredValue.from_dict(p["mt"]["value"])
    assert v.inferred and v.extraction_method.value == "inference"
    assert v.source_id == TABLE_SID and v.page == 4
    assert v.value == {"lat": 32.7812, "lon": -79.9431}


def test_cli_writes_the_conflicts_file(extracted, tmp_path):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps(list(CATALOG.values())))
    dest, conflicts = tmp_path / "sites", tmp_path / "review" / "well_id_conflicts.json"
    assert wells.main(["--extracted", str(extracted), "--catalog", str(cat), "--out-dir", str(dest),
                       "--conflicts", str(conflicts)]) == 0
    c = json.loads(conflicts.read_text())
    assert c["count"] == 1 and "about" in c and "generated" not in c


def test_matched_properties_are_documented(out):
    for f in out["wells"]["features"]:
        assert set(f["properties"]) <= set(wells.KEYS)
