import json
from pathlib import Path

import pytest

from harvest import catalog

FIX = Path(__file__).parent / "fixtures" / "catalog"


def test_parse_product_page():
    info = catalog.parse_product_page((FIX / "proddesc_115922.html").read_text())
    assert info["bbox"] == [-80.625, 32.25, -80.5, 32.375]
    assert info["citation"].startswith("Doar, W.R., III, 2000")
    assert info["keywords"] == ["surficial", "Quaternary", "map", "geologic map", "geology"]
    assert info["downloads"] == {
        "gems": ["https://ngmdb.usgs.gov/ngm-bin/gems_download.pl?id=2706&pid=115922"],
        "pdf": ["https://pubs.usgs.gov/of/2013/1030/pdf/ofr2013-1030.pdf"],
        "doi": ["https://doi.org/10.3133/ofr20131030"],
    }


def test_parse_product_page_without_metadata():
    assert catalog.parse_product_page("<html></html>") == {
        "bbox": None, "citation": None, "keywords": [], "downloads": {}}


@pytest.mark.parametrize("series,publisher,expected", [
    ("Open-File Report 257", "South Carolina Geological Survey", "SCGS OFR-257"),
    ("Open-File Report OFR-137", "South Carolina Geological Survey", "SCGS OFR-137"),
    ("Geologic Quadrangle Map GQM-5", "South Carolina Geological Survey", "SCGS GQM-5"),
    ("Map Series MS-27", "South Carolina Geological Survey", "SCGS MS-27"),
    ("OFR-137", "SCGS", "SCGS OFR-137"),
    ("GQM-5", "SCGS", "SCGS GQM-5"),
    ("Open-File Report 2013-1030", "U.S. Geological Survey", "USGS OFR-2013-1030"),
    ("Miscellaneous Investigations Series Map I-1935", "U.S. Geological Survey", "USGS I-1935"),
    ("", "U.S. Geological Survey", None),
    ("Bulletin 16", "Some Society", None),
])
def test_series_key(series, publisher, expected):
    assert catalog.series_key(series, publisher) == expected


@pytest.mark.parametrize("scale,expected", [
    ("1:24,000", 24000), ("1:100,000", 100000), ("24000", 24000), (24000, 24000),
    ("", None), (None, None), ("various", None),
])
def test_scale_denominator(scale, expected):
    assert catalog.scale_denominator(scale) == expected


NGMDB_ROWS = [
    {"id": 115922, "title": "Geologic Map of the St. Phillips Island Quadrangle", "authors": "Doar, W.R., III",
     "year": 2000, "series": "Open-File Report 257", "published_by": "South Carolina Geological Survey",
     "scale": "1:24,000", "online": "True", "gis": 1, "formats": ""},
    {"id": 77448, "title": "Geologic map of the Fort Pulaski quadrangle", "authors": "Doar, W.R., III",
     "year": 2002, "series": "Geologic Quadrangle Map GQM-5", "published_by": "South Carolina Geological Survey",
     "scale": "1:24,000", "online": "False", "gis": None, "formats": ""},
    {"id": 1, "title": "A research paper on the Cooper Group", "authors": "Weems, R.E.", "year": 1998,
     "series": "Geological Society of America Abstracts", "published_by": "Geological Society of America",
     "scale": "", "online": "True", "gis": None, "formats": "PDF"},
]
SCGS_INDEX = [
    {"OBJECTID": 6, "QUADNAME": "FORT PULASKI", "TILE_NAME": "FORTP", "Title": "Geologic map of the Fort Pulaski quadrangle",
     "Author": "Doar", "Map_Year": 2002, "Pub_1": "GQM-5", "Pub_2": " ", "Series": "Geologic Quadrangle Map",
     "Scale": 24000, "Mapped_By": "SCGS", "PROVINCE": "COASTAL PLAIN", "Hyperlink": "https://www.dnr.sc.gov/geology/publications.html"},
    {"OBJECTID": 7, "QUADNAME": "NOWHERE", "TILE_NAME": "NOWHE", "Title": "Geology of Nowhere", "Author": "X",
     "Map_Year": 1970, "Pub_1": "MS-99", "Pub_2": " ", "Series": "Map Series", "Scale": 24000, "Mapped_By": "SCGS",
     "PROVINCE": "PIEDMONT", "Hyperlink": " "},
    {"OBJECTID": 8, "QUADNAME": "UNMAPPED", "TILE_NAME": "UNMAP", "Title": " ", "Author": " ", "Map_Year": 0,
     "Pub_1": " ", "Pub_2": " ", "Series": " ", "Scale": 0, "Mapped_By": " ", "PROVINCE": "PIEDMONT", "Hyperlink": " "},
]
SCGS_GIS = [{"Pub_1": "GQM-5", "GIS_Available": "Yes"}, {"Pub_1": "MS-99", "GIS_Available": "\bNo"}]
FTP = ["ftp://ftpdata.dnr.sc.gov/gisdata/glc/fortp07glc_poly.zip", "ftp://ftpdata.dnr.sc.gov/gisdata/glc/fortp07glc_line.zip"]
THEMES = {"bedrock": {77448}, "surficial": {115922, 77448}}
PAGES = {115922: catalog.parse_product_page((FIX / "proddesc_115922.html").read_text())}


def build():
    return catalog.build_catalog(
        ngmdb_rows=NGMDB_ROWS, themes=THEMES, pages=PAGES, scgs_index=SCGS_INDEX, scgs_gis=SCGS_GIS,
        ftp_links=FTP, retrieved_at="2026-10-03T00:00:00+00:00")


def by_id(records):
    return {r["id"]: r for r in records}


def test_build_catalog_merges_ngmdb_and_scgs_records():
    recs = by_id(build())
    fp = recs["ngmdb:77448"]
    assert fp["series_key"] == "SCGS GQM-5"
    assert fp["themes"] == ["bedrock", "surficial"]
    assert fp["quadrangles"] == ["FORT PULASKI"]
    assert fp["availability"]["gis"] is True  # from the SCGS GIS table
    assert fp["availability"]["scgs_ftp"] == sorted(FTP)
    sources = [p["source_id"] for p in fp["provenance"]]
    assert sources == ["ngmdb-catalog", "scgs-24k-index", "scgs-24k-gis-table", "scdnr-ftp"]
    assert fp["provenance"][1]["locator"] == "OBJECTID=6"


def test_scgs_only_maps_are_kept_and_unmapped_quads_skipped():
    recs = by_id(build())
    assert "scgs:MS-99" in recs
    ms = recs["scgs:MS-99"]
    assert ms["title"] == "Geology of Nowhere" and ms["year"] == 1970 and ms["scale"] == 24000
    assert ms["availability"]["gis"] is False
    assert ms["provenance"][0]["source_id"] == "scgs-24k-index"
    assert not any(r.get("quadrangles") == ["UNMAPPED"] for r in recs.values())


def test_product_page_details_and_research_papers():
    recs = by_id(build())
    sp = recs["ngmdb:115922"]
    assert sp["bbox"] == [-80.625, 32.25, -80.5, 32.375]
    assert sp["availability"]["gems_download"].endswith("pid=115922")
    assert sp["availability"]["online"] is True
    paper = recs["ngmdb:1"]
    assert paper["kind"] == "publication"
    assert recs["ngmdb:77448"]["kind"] == "map"


def test_every_record_has_provenance():
    for r in build():
        assert r["provenance"], r["id"]
        for p in r["provenance"]:
            assert p["source_id"] and p["locator"]
            assert p["extraction_method"] == "catalog_import"
            assert p["confidence"] == 1.0
            assert p["retrieved_at"] == "2026-10-03T00:00:00+00:00"


def test_summary_counts():
    s = catalog.summarize(build())
    assert s["records"] == 4
    assert s["maps"] == 3
    assert s["with_gis"] == 2
    assert s["by_theme"] == {"bedrock": 1, "surficial": 2}


@pytest.mark.parametrize("pub,series,mapped_by,expected", [
    ("GQM-5", "Geologic Quadrangle Map", "SCGS", "SCGS GQM-5"),
    ("GQM-9", "Geologic Quadrangle Map", "USGS", "SCGS GQM-9"),
    ("56", "Geologic Quadrangle Map", "USGS", "SCGS GQM-56"),
    ("OFR-137", "Open File Report", "SCGS", "SCGS OFR-137"),
    ("2006-1238", "USGS Open-File Report", "USGS", "USGS OFR-2006-1238"),
    ("OFR 80-226", "Open File Report", "USGS", "USGS OFR-80-226"),
    ("I-1935", "USGS Miscellaneous Investigations Series Map", "USGS", "USGS I-1935"),
    ("EQM-1", "Edmap Quadrangle Map", "EDMAP", "EDMAP EQM-1"),
    ("draft", " ", "STATEMAP", None),
    (" ", " ", " ", None),
])
def test_scgs_index_key(pub, series, mapped_by, expected):
    row = {"Pub_1": pub, "Series": series, "Mapped_By": mapped_by}
    assert catalog._scgs_index_key(row) == expected


def test_draft_maps_are_listed_as_drafts():
    draft = {"OBJECTID": 9, "QUADNAME": "DRAFTVILLE", "TILE_NAME": "DRAFT", "Title": " ", "Author": " ",
             "Map_Year": 0, "Pub_1": "draft", "Pub_2": " ", "Series": " ", "Scale": 24000, "Mapped_By": "STATEMAP",
             "PROVINCE": "PIEDMONT", "Hyperlink": " "}
    recs = by_id(catalog.build_catalog(NGMDB_ROWS, THEMES, PAGES, SCGS_INDEX + [draft], SCGS_GIS, FTP,
                                       "2026-10-03T00:00:00+00:00"))
    d = recs["scgs-draft:DRAFT"]
    assert d["status"] == "draft"
    assert d["quadrangles"] == ["DRAFTVILLE"]
    assert d["publisher"] == "STATEMAP"
    assert recs["ngmdb:77448"]["status"] == "published"


def test_kind_needs_a_map_title_theme_or_quadrangle():
    rows = NGMDB_ROWS + [{"id": 2, "title": "Low-flow frequency of selected streams", "authors": "A",
                          "year": 1990, "series": "Water-Resources Investigations Report 90-1",
                          "published_by": "U.S. Geological Survey", "scale": "1:1,951,000", "online": "True",
                          "gis": None, "formats": ""}]
    recs = by_id(catalog.build_catalog(rows, THEMES, PAGES, SCGS_INDEX, SCGS_GIS, FTP, "t"))
    assert recs["ngmdb:2"]["kind"] == "publication"
    assert recs["ngmdb:115922"]["kind"] == "map"


# --- exclusions (config/catalog_exclude.json) ----------------------------------

ROOT = Path(__file__).resolve().parent.parent


def test_excluded_ids_reads_ids_and_reasons(tmp_path):
    path = tmp_path / "exclude.json"
    path.write_text(json.dumps({"exclude": [{"id": "ngmdb:1", "reason": "not geology"}]}))
    assert catalog.excluded_ids(path) == {"ngmdb:1"}
    assert catalog.excluded_ids(tmp_path / "missing.json") == set()


def test_build_catalog_drops_excluded_ids():
    recs = by_id(catalog.build_catalog(NGMDB_ROWS, THEMES, PAGES, SCGS_INDEX, SCGS_GIS, FTP, "t",
                                       exclude={"ngmdb:1"}))
    assert "ngmdb:1" not in recs
    assert "ngmdb:77448" in recs


def test_exclusion_list_is_well_formed():
    data = json.loads((ROOT / "config" / "catalog_exclude.json").read_text())
    ids = [e["id"] for e in data["exclude"]]
    assert ids and len(ids) == len(set(ids))
    for e in data["exclude"]:
        assert e["reason"], e["id"]
    assert catalog.excluded_ids() == set(ids)


def test_committed_catalog_has_no_excluded_records():
    records = json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text())
    assert not {r["id"] for r in records} & catalog.excluded_ids()
    summary = json.loads((ROOT / "data" / "catalog" / "summary.json").read_text())
    assert summary["records"] == len(records)


# --- corrections (config/catalog_corrections.json) -----------------------------

CORRECTIONS = [
    {"id": "ngmdb:1", "field": "authors", "old": "Weems, R.E.", "new": "Weems, R.E., Jr.",
     "reason": "typo", "inferred": False},
    {"id": "ngmdb:77448", "field": "themes", "old": ["bedrock", "surficial"], "new": [],
     "reason": "water report", "inferred": True},
    {"id": "ngmdb:115922", "field": "kind", "old": "map", "new": "publication", "reason": "a report"},
]


def test_corrections_are_applied_with_provenance():
    recs = by_id(catalog.build_catalog(NGMDB_ROWS, THEMES, PAGES, SCGS_INDEX, SCGS_GIS, FTP, "t",
                                       corrections=CORRECTIONS))
    paper = recs["ngmdb:1"]
    assert paper["authors"] == "Weems, R.E., Jr."
    assert paper["corrections"] == [{"field": "authors", "old": "Weems, R.E.", "new": "Weems, R.E., Jr.",
                                     "reason": "typo", "inferred": False}]
    prov = paper["provenance"][-1]
    assert prov["source_id"] == "catalog-corrections"
    assert prov["locator"] == "config/catalog_corrections.json: authors"
    assert prov["extraction_method"] == "manual" and prov["confidence"] == 1.0
    assert prov["inferred"] is False
    fp = recs["ngmdb:77448"]
    assert fp["themes"] == []
    assert fp["kind"] == "map"  # still a map: it lists a quadrangle
    assert fp["provenance"][-1]["inferred"] is True
    assert recs["ngmdb:115922"]["kind"] == "publication"


def test_removing_themes_recomputes_kind():
    rows = NGMDB_ROWS + [{"id": 3, "title": "Streamflow of selected rivers", "authors": "A", "year": 1990,
                          "series": "", "published_by": "U.S. Geological Survey", "scale": "",
                          "online": "True", "gis": None, "formats": ""}]
    themes = THEMES | {"engineering": {3}}
    fix = [{"id": "ngmdb:3", "field": "themes", "old": ["engineering"], "new": [], "reason": "streamflow"}]
    assert by_id(catalog.build_catalog(rows, themes, PAGES, [], [], [], "t"))["ngmdb:3"]["kind"] == "map"
    assert by_id(catalog.build_catalog(rows, themes, PAGES, [], [], [], "t", corrections=fix))["ngmdb:3"]["kind"] \
        == "publication"


def test_corrections_are_idempotent_and_skip_changed_values():
    recs = catalog.build_catalog(NGMDB_ROWS, THEMES, PAGES, SCGS_INDEX, SCGS_GIS, FTP, "t", corrections=CORRECTIONS)
    before = json.dumps(recs, sort_keys=True)
    assert catalog.apply_corrections(recs, CORRECTIONS) == []  # already applied: nothing to do, nothing stale
    assert json.dumps(recs, sort_keys=True) == before
    stale = [{"id": "ngmdb:1", "field": "title", "old": "Something else", "new": "X", "reason": "r"},
             {"id": "ngmdb:404", "field": "title", "old": "a", "new": "b", "reason": "r"}]
    assert [s["id"] for s in catalog.apply_corrections(recs, stale)] == ["ngmdb:1", "ngmdb:404"]
    assert by_id(recs)["ngmdb:1"]["title"] == "A research paper on the Cooper Group"


def test_correction_list_is_well_formed():
    fixes = catalog.load_corrections()
    assert fixes
    seen = set()
    for c in fixes:
        assert set(c) <= {"id", "field", "old", "new", "reason", "inferred"}, c
        assert c["reason"] and c["old"] != c["new"], c
        assert c["field"] in ("authors", "citation", "title", "themes", "kind"), c
        assert (c["id"], c["field"]) not in seen, c
        seen.add((c["id"], c["field"]))
    assert catalog.load_corrections(Path("/nonexistent/corrections.json")) == []


def test_committed_catalog_has_corrections_applied():
    records = by_id(json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text()))
    for c in catalog.load_corrections():
        rec = records.get(c["id"])
        assert rec is not None, c["id"]  # corrections never delete a record
        assert rec[c["field"]] == c["new"], c
        assert {k: c[k] for k in ("field", "old", "new")} in [
            {k: x[k] for k in ("field", "old", "new")} for x in rec["corrections"]]
    assert records["ngmdb:25572"]["authors"].startswith("Dennehy, K.F.")
    assert "Wiloughby" not in records["ngmdb:100308"]["authors"]
    assert records["ngmdb:49178"]["kind"] == "publication"
    summary = json.loads((ROOT / "data" / "catalog" / "summary.json").read_text())
    fresh = json.loads(json.dumps(catalog.summarize(list(records.values()))))
    assert summary == fresh | {"retrieved_at": summary["retrieved_at"]}


def test_theme_corrections_follow_the_reading_list_rules():
    """Geology themes removed only from USGS reports the reading list already calls non-geologic."""
    from extract import reading_list

    records = by_id(json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text()))
    themed = [c for c in catalog.load_corrections() if c["field"] == "themes"]
    assert themed
    for c in themed:
        rec = records[c["id"]]
        assert c["new"] == [] and c["inferred"] is True, c
        assert rec["publisher"] == "U.S. Geological Survey", c["id"]
        assert reading_list.non_geologic_subject(rec["title"]), c["id"]


def test_non_geologic_subject():
    from extract import reading_list

    assert reading_list.non_geologic_subject("Magnitude and frequency of rural floods in South Carolina") == "floods"
    assert reading_list.non_geologic_subject("Water quality of the Coastal Plain aquifers") == "water quality"
    assert reading_list.non_geologic_subject("Geologic map of the water-quality site") is None
    assert reading_list.non_geologic_subject("Geologic map of the Bonneau quadrangle") is None


def test_reapplying_refreshes_reason_and_inferred_flag():
    recs = catalog.build_catalog(NGMDB_ROWS, THEMES, PAGES, SCGS_INDEX, SCGS_GIS, FTP, "t", corrections=CORRECTIONS)
    changed = [dict(CORRECTIONS[0], reason="typo; title page shows Jr.", inferred=True)]
    assert catalog.apply_corrections(recs, changed) == []
    paper = by_id(recs)["ngmdb:1"]
    assert paper["corrections"] == [{"field": "authors", "old": "Weems, R.E.", "new": "Weems, R.E., Jr.",
                                     "reason": "typo; title page shows Jr.", "inferred": True}]
    fixes = [p for p in paper["provenance"] if p["source_id"] == "catalog-corrections"]
    assert len(fixes) == 1 and fixes[0]["inferred"] is True


@pytest.mark.parametrize("rid,wrong,right", [
    ("ngmdb:6377", "Smth, C.C.", "Smith, C.C."),
    ("ngmdb:94281", "Niwendorp, C.A.", "Niewendorp, C.A."),
    ("ngmdb:33345", "O'brien, T.F.", "O'Brien, T.F."),
    ("ngmdb:4863", "Renkin, R.A.", "Renken, R.A."),
    ("ngmdb:42981", "Wagner, H.D.", "Wagener, H.D."),
    ("ngmdb:74872", "Clark, J.W.", "Clarke, J.W."),
    ("ngmdb:77556", "Ransom, W.A.", "Ranson, W.A."),
    ("ngmdb:77560", "Ransom, W.A.", "Ranson, W.A."),
    ("ngmdb:83395", "van Stall, C.R.", "van Staal, C.R."),
    ("ngmdb:13597", "Welch, L.O.", "Wilch, L.O."),
    ("ngmdb:43718", "Weise, D.S.", "Wiese, D.S."),
    ("ngmdb:7374", "Hooper, M.G.", "Hopper, M.G."),
    ("ngmdb:74709", "Gorsz, A.E.", "Grosz, A.E."),
])
def test_committed_catalog_has_author_name_fixes(rid, wrong, right):
    rec = by_id(json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text()))[rid]
    for field in ("authors", "citation"):
        assert wrong not in rec[field] and right in rec[field], (rid, field)


def test_unconfirmed_names_are_left_alone():
    records = by_id(json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text()))
    assert "Wyrik, R.F." in records["ngmdb:56440"]["authors"]
    assert "Stockl, D.F." in records["ngmdb:113142"]["authors"]
    assert "Books, K.G." in records["ngmdb:74376"]["authors"]
