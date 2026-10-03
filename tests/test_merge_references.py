import json

from merge import references

CATALOG = [
    {"id": "ngmdb:10009", "title": "Geology of the Cainhoy ... quadrangles", "year": 1993, "scale": 24000,
     "bbox": [-80.0, 32.75, -79.75, 33.0], "citation": "Weems, R.E., and Lemon, E.M., 1993, Geology ...",
     "ngmdb_url": "https://ngmdb.usgs.gov/Prodesc/proddesc_10009.htm", "kind": "map", "status": "published",
     "availability": {"doi": None, "pdf": []}},
    {"id": "ngmdb:2", "title": "A report with no map scale", "year": 2001, "scale": None,
     "bbox": [-80.123456789, 32.5, -79.5, 33.25], "citation": None, "ngmdb_url": None, "kind": "publication",
     "status": "published", "availability": {"doi": "https://doi.org/10.3133/x", "pdf": []}},
    {"id": "ngmdb:3", "title": "No footprint", "year": 1980, "scale": 250000, "bbox": None, "citation": "C, 1980",
     "ngmdb_url": "https://ngmdb.usgs.gov/Prodesc/proddesc_3.htm", "kind": "map", "status": "published",
     "availability": {}},
    {"id": "scgs-draft:7", "title": "Draft map", "year": 2024, "scale": 24000, "bbox": [-81, 34, -80.875, 34.125],
     "citation": "D, 2024", "ngmdb_url": None, "kind": "map", "status": "draft",
     "availability": {"doi": None, "pdf": ["http://example.test/not-https.pdf"]}},
]


def test_records_are_compact_and_skip_records_without_a_footprint():
    out = references.build(CATALOG)
    recs = {r["id"]: r for r in out["records"]}
    assert set(recs) == {"ngmdb:10009", "ngmdb:2", "scgs-draft:7"}
    assert recs["ngmdb:10009"] == {
        "id": "ngmdb:10009", "citation": "Weems, R.E., and Lemon, E.M., 1993, Geology ...", "year": 1993,
        "scale": 24000, "bbox": [-80.0, 32.75, -79.75, 33.0],
        "url": "https://ngmdb.usgs.gov/Prodesc/proddesc_10009.htm"}


def test_citation_falls_back_to_title_and_url_to_doi_and_bbox_is_rounded():
    r = next(r for r in references.build(CATALOG)["records"] if r["id"] == "ngmdb:2")
    assert r["citation"] == "A report with no map scale"
    assert r["url"] == "https://doi.org/10.3133/x"
    assert r["bbox"] == [-80.1235, 32.5, -79.5, 33.25]
    assert "scale" not in r  # nulls are left out


def test_only_https_links_are_kept_and_drafts_are_marked():
    r = next(r for r in references.build(CATALOG)["records"] if r["id"] == "scgs-draft:7")
    assert "url" not in r
    assert r["draft"] is True


def test_provenance_points_back_to_the_catalog():
    prov = references.build(CATALOG)["provenance"]
    assert prov["source_id"] == "sc-catalog"
    assert prov["locator"] == "records[].id = id in data/catalog/sc_catalog.json"
    assert prov["extraction_method"] == "catalog_import"
    assert prov["confidence"] == 1.0


def test_write_creates_a_small_json_file(tmp_path):
    path = references.write(CATALOG, tmp_path / "references.json")
    data = json.loads(path.read_text())
    assert len(data["records"]) == 3
    assert "\n" not in path.read_text()  # compact


def test_records_covering_a_point_are_ranked_by_scale_then_recency():
    recs = references.build(CATALOG)["records"]
    hits = references.covering(recs, -79.9, 32.9)
    assert [r["id"] for r in hits] == ["ngmdb:10009", "ngmdb:2"]
    assert references.covering(recs, -78.0, 32.0) == []


def test_a_footprint_larger_than_the_state_ranks_as_unknown_scale():
    wide = {"id": "ngmdb:9", "citation": "J, 1956", "year": 1956, "scale": 26670, "bbox": [-95, 27.5, -73.8, 44]}
    recs = references.build(CATALOG)["records"] + [wide]
    assert [r["id"] for r in references.covering(recs, -79.9, 32.9)] == ["ngmdb:10009", "ngmdb:2", "ngmdb:9"]
