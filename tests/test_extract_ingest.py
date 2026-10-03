import json
from pathlib import Path

import pytest

from extract import ingest
from model.provenance import StoredValue
from model.units import Lexicon

# --- quote matching ----------------------------------------------------------


def page(text, raw=None, method="pdf_text", n=1):
    return {"page": n, "text": text, "raw": raw if raw is not None else text, "method": method}


@pytest.mark.parametrize("text,quote,expected", [
    ("Qw      Wando Formation\n   clayey   sand", "Qw Wando Formation clayey sand", "exact"),
    ("consists of fine-grained sedi-\nment and shell", "fine-grained sediment and shell", "exact"),
    ("moderately well-\n   sorted sand", "moderately well-sorted sand", "exact"),
    ("ﬁne sand with ﬂaser bedding", "fine sand with flaser bedding", "exact"),
    ("the “upper” bed – Ten Mile Hill", "the \"upper\" bed - Ten Mile Hill", "exact"),
    ("Wando Formation (late Pleistocene).", "Wando Formation (late Pleistocene)", "exact"),
    ("WANDO FORMATION", "Wando Formation", "exact"),
    ("Penholoway Formation", "Wando Formation", None),
])
def test_find_quote_pdf_text(text, quote, expected):
    assert ingest.find_quote(quote, page(text)) == expected


def test_find_quote_reading_order_text():
    layout = "The Wando Formation      Auger hole 12 was drilled\nunderlies the lowest      near the river."
    raw = "The Wando Formation underlies the lowest\n\nAuger hole 12 was drilled near the river."
    assert ingest.find_quote("Auger hole 12 was drilled near the river", page(layout, raw)) == "exact"


def test_find_quote_ocr_confusions():
    ocr = page("Wando Forrnation, clayey sand, 1OYR 5/6, as rnuch as 3O ft", method="ocr")
    assert ingest.find_quote("Wando Formation, clayey sand, 10YR 5/6, as much as 30 ft", ocr) == "ocr"


def test_find_quote_fuzzy_single_typo():
    p = page("The formation is composed of fossiliferous sandy limestone and calcareous clay.", method="ocr")
    assert ingest.find_quote("composed of fossilferous sandy limestone and calcareous clay", p) == "fuzzy"


@pytest.mark.parametrize("quote", [
    "is 42 ft thick in the type section in CC1 and reaches",   # digits swapped
    "of 416 and 441 ft in CC1 is designated as the type",     # one digit changed
])
def test_fuzzy_never_accepts_changed_numbers(quote):
    p = page("The Fishburne is 24 ft thick in the type section in CC1 and reaches 74 ft. "
             "The interval between depths of 416 and 440 ft in CC1 is designated as the type section.")
    assert ingest.find_quote(quote, p) is None


def test_fuzzy_allows_ocr_digit_confusions():
    p = page("The Fishburne is 24 ft thick in the type secton in CC1 and reaches 7O ft maximum.", method="ocr")
    assert ingest.find_quote("is 24 ft thick in the type section in CC1 and reaches 70 ft", p) == "fuzzy"


def test_find_quote_short_quote_needs_exact():
    p = page("Qwa  Wando", method="ocr")
    assert ingest.find_quote("Qwb", p) is None


# --- full ingest -------------------------------------------------------------

RECORD = {"id": "ngmdb:10009", "title": "Geology of the Cainhoy quadrangle", "year": 1993, "scale": 24000,
          "publisher": "U.S. Geological Survey", "citation": "Weems and Lemon, 1993", "kind": "map",
          "status": "published"}
PUB = {**RECORD, "id": "ngmdb:20", "scale": None, "kind": "publication", "publisher": "Some Society"}

TEXT = {
    "source_id": "ngmdb:10009",
    "files": [{"url": "https://ngmdb.usgs.gov/x.pdf", "path": "/tmp/x.pdf", "sha256": "ab" * 32, "pages": 3,
               "first_page": 1, "via": "ngmdb_scan"}],
    "pages": [
        {"page": 1, "file": 0, "file_page": 1, "method": "pdf_text",
         "text": "Qw   Wando Formation (late Pleistocene)\nClayey sand, as much as 30 ft thick.",
         "raw": "Qw Wando Formation (late Pleistocene) Clayey sand, as much as 30 ft thick."},
        {"page": 2, "file": 0, "file_page": 2, "method": "ocr",
         "text": "AUGER HOLE 12  0-4 ft  sand, yellowish brown (1OYR 5/6)  SM",
         "raw": "AUGER HOLE 12  0-4 ft  sand, yellowish brown (1OYR 5/6)  SM"},
        {"page": 3, "file": 0, "file_page": 3, "method": "pdf_text",
         "text": "The Charleston fault strikes N30E and dips 60SE.", "raw": ""},
    ],
}


def v(value, page, quote, inferred=False, **kw):
    return {"value": value, "page": page, "quote": quote, "inferred": inferred, **kw}


RESULT = {
    "schema_version": 1,
    "source_id": "ngmdb:10009",
    "packets": ["packet-01"],
    "reader": "test",
    "units": [{
        "map_symbol": v("Qw", 1, "Qw   Wando Formation"),
        "name": v("Wando Formation", 1, "Wando Formation (late Pleistocene)"),
        "age": v("late Pleistocene", 1, "(late Pleistocene)"),
        "thickness": v("as much as 30 ft", 1, "as much as 30 ft thick"),
        "rank": v("Formation", 1, "Wando Formation", inferred=True),
        "group": "not stated",
    }],
    "observations": [{
        "kind": "auger_hole",
        "label": v("12", 2, "AUGER HOLE 12", table=True),
        "intervals": [{
            "top": v("0", 2, "0-4 ft", units="ft", table=True),
            "bottom": v("4", 2, "0-4 ft", units="ft", table=True),
            "munsell": v("10YR 5/6", 2, "yellowish brown (10YR 5/6)", table=True),
            "uscs": v("SM", 2, "SM", table=True),
        }],
    }],
    "structures": [{
        "kind": "fault",
        "name": v("Charleston fault", 3, "The Charleston fault"),
        "strike_dip": v("N30E, 60SE", 3, "strikes N30E and dips 60SE"),
        "sense": v("reverse", 3, "reverse motion on the fault"),       # not on the page
        "certainty": v("certain", 2, "Charleston fault strikes N30E"),  # on page 3, not 2
    }],
    "groundwater": [],
    "references": [],
}


@pytest.fixture
def env(tmp_path):
    text_dir = tmp_path / ".cache" / "text"
    text_dir.mkdir(parents=True)
    (text_dir / "ngmdb_10009.json").write_text(json.dumps(TEXT))
    res = tmp_path / "result.json"
    res.write_text(json.dumps(RESULT))
    lex = Lexicon([{"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"}])
    return dict(text_dir=text_dir, out_dir=tmp_path / "data" / "extracted", review_dir=tmp_path / "data" / "review",
                catalog={r["id"]: r for r in (RECORD, PUB)}, lexicon=lex, done_dir=tmp_path / ".checkpoints" / "extract"
                ), res


def _out(env):
    return json.loads((env["out_dir"] / "ngmdb_10009.json").read_text())


def test_ingest_stores_provenance_for_every_value(env):
    e, res = env
    summary = ingest.ingest([res], **e)
    out = _out(e)
    unit = out["units"][0]
    for field in ("map_symbol", "name", "age", "thickness", "rank"):
        sv = StoredValue.from_dict(unit[field])  # round-trips: provenance is complete
        assert sv.source_id == "ngmdb:10009" and sv.page == 1 and sv.extraction_method.value == "llm"
        assert 0 < sv.confidence <= 1
        assert unit[field]["quote_match"] == "exact"
    assert unit["rank"]["inferred"] is True and unit["name"]["inferred"] is False
    assert "group" not in unit  # 'not stated' is not stored
    assert summary["values"] == 14 and summary["stored"] == 12
    assert out["files"][0]["url"] == "https://ngmdb.usgs.gov/x.pdf" and "path" not in out["files"][0]
    assert (e["done_dir"] / "ngmdb_10009.json").exists()


def test_ingest_normalizes(env):
    e, res = env
    ingest.ingest([res], **e)
    out = _out(e)
    unit = out["units"][0]
    assert unit["thickness"]["normalized"]["max_ft"] == 30.0 and unit["thickness"]["normalized"]["min_ft"] is None
    assert unit["age"]["normalized"] == {"younger_ma": 0.0117, "older_ma": 0.129, "inferred": True,
                                         "source": "International Chronostratigraphic Chart v2023/09"}
    assert unit["name"]["normalized"]["canonical"] == "Wando"
    iv = out["observations"][0]["intervals"][0]
    assert iv["bottom"]["normalized"]["max_ft"] == 4.0  # number + separate units
    assert iv["munsell"]["normalized"]["notation"] == "10YR 5/6"
    assert iv["uscs"]["normalized"] == ["SM"]
    assert out["structures"][0]["strike_dip"]["normalized"]["strike"] == 30


def test_ingest_rejects_unverified_quotes_into_review(env):
    e, res = env
    ingest.ingest([res], **e)
    out = _out(e)
    fault = out["structures"][0]
    assert "sense" not in fault and "certainty" not in fault
    q = json.loads((e["review_dir"] / "queue.json").read_text())["items"]
    problems = {(i["path"], i["problem"]) for i in q}
    assert ("structures[0].sense", "quote_not_found") in problems
    assert ("structures[0].certainty", "wrong_page") in problems
    wrong = next(i for i in q if i["problem"] == "wrong_page")
    assert wrong["found_page"] == 3 and wrong["source_id"] == "ngmdb:10009"


def test_confidence_formula(env):
    e, res = env
    ingest.ingest([res], **e)
    out = _out(e)
    # map at 1:24,000 -> 0.95; pdf_text 1.0; exact 1.0; unchecked 0.85; not inferred.
    assert out["units"][0]["name"]["confidence"] == round(0.95 * 0.85, 3)
    # inferred
    assert out["units"][0]["rank"]["confidence"] == round(0.95 * 0.85 * 0.8, 3)
    # OCR page, matched through OCR confusions (1OYR vs 10YR). A boring log is not
    # generalized by map scale: S is the publisher weight (USGS 0.85), not 0.95.
    mun = out["observations"][0]["intervals"][0]["munsell"]
    assert mun["quote_match"] == "ocr"
    assert mun["confidence"] == round(0.85 * 0.9 * 0.95 * 0.85, 3)
    assert ingest.source_weight(PUB) == 0.7
    assert ingest.source_weight({**PUB, "publisher": "U.S. Geological Survey"}) == 0.85
    assert ingest.source_weight({**PUB, "status": "draft"}) == 0.6
    # Scale applies only to map-unit descriptions read from a map sheet.
    small = {**RECORD, "scale": 875000}
    assert ingest.source_weight(small, "units", map_sheet=True) == 0.45
    assert ingest.source_weight(small, "units", map_sheet=False) == 0.85  # report text
    assert ingest.source_weight(small, "observations", map_sheet=True) == 0.85
    assert ingest.source_weight(RECORD, "units", map_sheet=True) == 0.95
    assert ingest.source_weight(RECORD, "references", map_sheet=True) == 0.85


def test_map_sheet_pages():
    files = [{"url": "https://pubs.usgs.gov/of/1985/0274/plate-1.pdf", "via": "pubs_usgs", "pages": 1, "first_page": 1},
             {"url": "https://pubs.usgs.gov/of/1985/0274/report.pdf", "via": "pubs_usgs", "pages": 3, "first_page": 2},
             {"url": "https://ngmdb.usgs.gov/ngm-bin/pdp/download.pl?q=1_2_2", "via": "ngmdb_scan", "pages": 1,
              "first_page": 5}]
    assert ingest.map_sheet_pages({"files": files}) == {1, 5}


def test_verify_agree_and_disagree(env, tmp_path):
    e, res = env
    ver = tmp_path / "verify.json"
    ver.write_text(json.dumps({"source_id": "ngmdb:10009", "checks": [
        {"path": "units[0].name", "verdict": "agree"},
        {"path": "units[0].map_symbol", "verdict": "disagree", "value": "Qwa", "note": "symbol is Qwa"},
        {"path": "units[0].age", "verdict": "unclear"},
    ]}))
    ingest.ingest([res], verify_path=ver, **e)
    unit = _out(e)["units"][0]
    assert unit["name"]["verification"] == "agree" and unit["name"]["confidence"] == 0.95
    assert unit["map_symbol"]["verification"] == "disagree"
    assert unit["map_symbol"]["confidence"] == round(0.95 * 0.4, 3)
    assert unit["age"]["confidence"] == round(0.95 * 0.7, 3)
    q = json.loads((e["review_dir"] / "queue.json").read_text())["items"]
    dis = next(i for i in q if i["problem"] == "verify_disagree")
    assert dis["verify"]["value"] == "Qwa"
    assert any(i["problem"] == "verify_unclear" for i in q)


def test_reingest_replaces_review_items_for_that_source(env):
    e, res = env
    e["review_dir"].mkdir(parents=True)
    (e["review_dir"] / "queue.json").write_text(json.dumps({"items": [
        {"source_id": "ngmdb:1", "path": "units[0].name", "problem": "quote_not_found"},
        {"source_id": "ngmdb:10009", "path": "old", "problem": "quote_not_found"}]}))
    ingest.ingest([res], **e)
    ingest.ingest([res], **e)
    items = json.loads((e["review_dir"] / "queue.json").read_text())["items"]
    assert sum(i["source_id"] == "ngmdb:1" for i in items) == 1
    assert not any(i["path"] == "old" for i in items)
    assert len([i for i in items if i["source_id"] == "ngmdb:10009"]) == 2


def test_invalid_result_writes_nothing(env, tmp_path):
    e, _ = env
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**RESULT, "units": [{"name": {"value": "x", "page": 1}}]}))
    with pytest.raises(ingest.IngestError) as err:
        ingest.ingest([bad], **e)
    assert "units[0].name" in str(err.value)
    assert not e["out_dir"].exists()


def test_unknown_source_or_missing_text(env, tmp_path):
    e, _ = env
    other = tmp_path / "other.json"
    other.write_text(json.dumps({**RESULT, "source_id": "ngmdb:404"}))
    with pytest.raises(ingest.IngestError, match="not in the catalog"):
        ingest.ingest([other], **e)
    pub = tmp_path / "pub.json"
    pub.write_text(json.dumps({**RESULT, "source_id": "ngmdb:20"}))
    with pytest.raises(ingest.IngestError, match="next_batch"):
        ingest.ingest([pub], **e)


def test_inexact_quote_on_text_layer_page_is_reviewed(env, tmp_path):
    e, _ = env
    r = json.loads(json.dumps(RESULT))
    r["units"][0]["description"] = v("clayey sand, as rnuch as 30 ft", 1, "Clayey sand, as rnuch as 30 ft")
    p = tmp_path / "r.json"
    p.write_text(json.dumps(r))
    ingest.ingest([p], **e)
    assert _out(e)["units"][0]["description"]["quote_match"] == "ocr"
    q = json.loads((e["review_dir"] / "queue.json").read_text())["items"]
    assert any(i["path"] == "units[0].description" and i["problem"] == "inexact_quote" for i in q)


def test_page_out_of_range_is_review_not_crash(env, tmp_path):
    e, _ = env
    r = json.loads(json.dumps(RESULT))
    r["units"][0]["name"]["page"] = 99
    p = tmp_path / "r.json"
    p.write_text(json.dumps(r))
    ingest.ingest([p], **e)
    q = json.loads((e["review_dir"] / "queue.json").read_text())["items"]
    assert any(i["path"] == "units[0].name" and i["problem"] == "quote_not_found" for i in q)


def test_two_results_for_one_document_are_combined(env, tmp_path):
    e, res = env
    part2 = tmp_path / "part2.json"
    part2.write_text(json.dumps({**RESULT, "packets": ["packet-02"], "units": [], "observations": [],
                                 "structures": [], "references": [
                                     {"citation": v("Charleston fault", 3, "The Charleston fault strikes")}]}))
    ingest.ingest([res, part2], **e)
    out = _out(e)
    assert out["packets"] == ["packet-01", "packet-02"]
    assert len(out["references"]) == 1 and len(out["units"]) == 1


def test_verify_sample_includes_all_table_values_and_a_tenth():
    paths = ingest.verify_sample(RESULT, fraction=0.1)
    table = {"observations[0].label", "observations[0].intervals[0].top", "observations[0].intervals[0].bottom",
             "observations[0].intervals[0].munsell", "observations[0].intervals[0].uscs"}
    assert table <= set(paths)
    assert len(paths) == len(table) + 1  # ceil(10% of the 9 others)
    assert paths == ingest.verify_sample(RESULT, fraction=0.1)  # deterministic


def test_never_writes_text_under_data(env):
    e, res = env
    ingest.ingest([res], **e)
    blob = (e["out_dir"] / "ngmdb_10009.json").read_text()
    assert "Clayey sand, as much as 30 ft thick." not in blob  # page text is not copied, only short quotes
