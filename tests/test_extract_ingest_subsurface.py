"""Subsurface values (surfaces, contours, sections, observation datums) through ingest."""

import json
from pathlib import Path

import pytest

from extract import ingest, schema
from model.provenance import ExtractionMethod, StoredValue
from model.units import Lexicon

ROOT = Path(__file__).resolve().parent.parent
SID = "ngmdb:77"
RECORD = {"id": SID, "title": "Subsurface geology near Charleston", "year": 1990, "scale": None,
          "publisher": "U.S. Geological Survey", "citation": "C", "kind": "publication", "status": "published"}
PAGES = {
    1: "Table 2. Altitude of the top of the Cooper Marl, in feet relative to NGVD 29\n"
       "Well      Lat      Long      Top\nCHN-14   324512   0795841   -62",
    2: "The base of the surficial aquifer is about 35 ft below land surface near Mount Pleasant.",
    3: "Figure 5. Structure contours on the top of the Santee Limestone. Contour interval 20 feet. "
       "Datum is sea level. Contours -100 and -120 cross Charleston County.",
    4: "Plate 2. Section A-A' from Summerville to Folly Beach (32.655, -79.94). Vertical exaggeration x 100. "
       "Wells CHN-14 and DOR-37. Ashley Formation from 0 to 12 mi, top -40 ft.",
    5: "Well DOR-37. Land surface 42 ft above NAVD 88. Depths in feet below land surface. 0-10 ft sand.",
}


def v(value, page, quote, inferred=False, **kw):
    return {"value": value, "page": page, "quote": quote, "inferred": inferred, **kw}


RESULT = {
    "schema_version": 1, "source_id": SID, "packets": ["packet-01"], "reader": "test",
    "units": [], "structures": [], "groundwater": [], "references": [],
    "observations": [{
        "kind": "well",
        "label": v("DOR-37", 5, "Well DOR-37"),
        "elevation": v("42 ft", 5, "Land surface 42 ft above NAVD 88"),
        "datum": v("NAVD 88", 5, "42 ft above NAVD 88"),
        "depth_reference": v("land surface", 5, "Depths in feet below land surface"),
        "intervals": [{"top": v("0 ft", 5, "0-10 ft sand"), "bottom": v("10 ft", 5, "0-10 ft sand")}],
    }],
    "surfaces": [{
        "surface": v("top of the Cooper Marl", 1, "Altitude of the top of the Cooper Marl"),
        "unit": v("Cooper Marl", 1, "top of the Cooper Marl"),
        "boundary": v("top", 1, "Altitude of the top of the Cooper Marl"),
        "elevation": v(-62, 1, "0795841   -62", units="ft", table=True),
        "datum": v("NGVD 29", 1, "in feet relative to NGVD 29"),
        "location": v("lat 324512, long 0795841", 1, "CHN-14   324512   0795841", table=True),
        "observation": v("CHN-14", 1, "CHN-14", table=True),
        "method": v("measured", 1, "Altitude of the top of the Cooper Marl", inferred=True),
    }, {
        "surface": v("base of the surficial aquifer", 2, "The base of the surficial aquifer"),
        "boundary": v("base", 2, "The base of the surficial aquifer"),
        "depth": v("about 35 ft", 2, "about 35 ft below land surface"),
        "datum": v("land surface", 2, "35 ft below land surface"),
        "location": v("near Mount Pleasant", 2, "near Mount Pleasant"),
        "method": v("stated", 2, "is about 35 ft below land surface"),
        "unit": v("Wando Formation", 2, "the Wando Formation is not here"),   # not on the page
    }],
    "contours": [{
        "kind": "structure",
        "surface": v("top of the Santee Limestone", 3, "Structure contours on the top of the Santee Limestone"),
        "interval": v("20 feet", 3, "Contour interval 20 feet"),
        "datum": v("sea level", 3, "Datum is sea level"),
        "values": [v(-100, 3, "Contours -100 and -120"), v(-120, 3, "Contours -100 and -120")],
        "area": v("Charleston County", 3, "cross Charleston County"),
        "figure": v("Figure 5", 3, "Figure 5. Structure contours"),
    }],
    "sections": [{
        "name": v("A-A'", 4, "Section A-A'"),
        "figure": v("Plate 2", 4, "Plate 2. Section A-A'"),
        "start": {"location": v("Summerville", 4, "from Summerville")},
        "end": {"location": v("Folly Beach", 4, "to Folly Beach"),
                "coordinates": v("32.655, -79.94", 4, "Folly Beach (32.655, -79.94)")},
        "vertical_exaggeration": v("x 100", 4, "Vertical exaggeration x 100"),
        "observations": [v("CHN-14", 4, "Wells CHN-14 and DOR-37"), v("DOR-37", 4, "Wells CHN-14 and DOR-37")],
        "units_along": [{"unit": v("Ashley Formation", 4, "Ashley Formation from 0 to 12 mi"),
                         "from_distance": v("0 mi", 4, "from 0 to 12 mi"),
                         "to_distance": v("12 mi", 4, "from 0 to 12 mi"),
                         "top_elevation": v("-40 ft", 4, "top -40 ft")}],
    }],
}


@pytest.fixture
def env(tmp_path):
    text = tmp_path / ".cache" / "text"
    text.mkdir(parents=True)
    (text / "ngmdb_77.json").write_text(json.dumps({"source_id": SID, "files": [
        {"url": "https://pubs.usgs.gov/x/report.pdf", "via": "pubs_usgs", "pages": 5, "first_page": 1}],
        "pages": [{"page": n, "file": 0, "file_page": n, "method": "pdf_text", "text": t, "raw": t}
                  for n, t in PAGES.items()]}))
    pk = tmp_path / ".cache" / "packets" / "ngmdb_77"
    pk.mkdir(parents=True)
    (pk / "index.json").write_text(json.dumps({"source_id": SID, "blocks": ["1", "2", "3", "4", "5"], "packets": [
        {"file": "packet-01.md", "pages": [1, 2, 3, 4, 5], "blocks": ["1", "2", "3", "4", "5"]}]}))
    kw = dict(text_dir=text, packets_dir=tmp_path / ".cache" / "packets", out_dir=tmp_path / "data" / "extracted",
              review_dir=tmp_path / "data" / "review", done_dir=tmp_path / ".checkpoints" / "extract",
              catalog={SID: RECORD}, lexicon=Lexicon([]))

    def run(res=RESULT, verify=None, **extra):
        p = tmp_path / "result.json"
        p.write_text(json.dumps(res))
        vp = None
        if verify is not None:
            vp = tmp_path / "verify.json"
            vp.write_text(json.dumps(verify))
        summary = ingest.ingest([p], verify_path=vp, **{**kw, **extra})
        out = json.loads((kw["out_dir"] / "ngmdb_77.json").read_text())
        queue = json.loads((kw["review_dir"] / "queue.json").read_text())["items"]
        return summary, out, queue
    return run


def test_result_is_valid():
    assert schema.validate(RESULT) == []


def test_new_sections_are_stored_with_provenance(env):
    summary, out, _ = env()
    s0 = out["surfaces"][0]
    for field in ("surface", "unit", "boundary", "elevation", "datum", "location", "observation", "method"):
        sv = StoredValue.from_dict(s0[field])
        assert sv.source_id == SID and sv.page == 1 and sv.extraction_method is ExtractionMethod.LLM
        assert 0 < sv.confidence <= 1 and s0[field]["quote"]
    assert s0["method"]["inferred"] is True and s0["elevation"]["inferred"] is False
    c = out["contours"][0]
    assert c["kind"] == "structure" and [x["value"] for x in c["values"]] == [-100, -120]
    sec = out["sections"][0]
    assert sec["start"]["location"]["value"] == "Summerville" and sec["end"]["coordinates"]["page"] == 4
    assert [x["value"] for x in sec["observations"]] == ["CHN-14", "DOR-37"]
    assert sec["units_along"][0]["top_elevation"]["value"] == "-40 ft"
    obs = out["observations"][0]
    assert obs["datum"]["value"] == "NAVD 88" and obs["depth_reference"]["value"] == "land surface"
    assert out["summary"]["stored"] == summary["stored"]


def test_new_sections_are_quote_checked(env):
    summary, out, queue = env()
    assert "unit" not in out["surfaces"][1]
    assert ("surfaces[1].unit", "quote_not_found") in {(i["path"], i["problem"]) for i in queue}
    assert summary["values"] == summary["stored"] + 1


def test_new_fields_are_normalized(env):
    _, out, _ = env()
    s0, s1 = out["surfaces"]
    assert s0["elevation"]["normalized"]["min_ft"] == -62.0           # sign kept
    assert s0["datum"]["normalized"] == "NGVD29"
    assert s1["depth"]["normalized"]["max_ft"] == 35.0 and s1["depth"]["normalized"]["approximate"] is True
    assert s1["datum"]["normalized"] == "land surface"
    c = out["contours"][0]
    assert c["interval"]["normalized"]["max_ft"] == 20.0 and c["datum"]["normalized"] == "MSL"
    assert c["values"][1]["normalized"] == -120.0
    sec = out["sections"][0]
    assert sec["vertical_exaggeration"]["normalized"] == 100.0
    assert sec["units_along"][0]["top_elevation"]["normalized"]["min_ft"] == -40.0
    assert out["observations"][0]["datum"]["normalized"] == "NAVD88"


def test_parsed_coordinates_are_a_separate_inferred_value(env):
    _, out, _ = env()
    loc = out["surfaces"][0]["location"]
    assert loc["value"] == "lat 324512, long 0795841" and loc["inferred"] is False  # the value as printed is kept
    d = loc["derived_coordinates"]
    sv = StoredValue.from_dict(d)
    assert sv.inferred is True and sv.extraction_method is ExtractionMethod.INFERENCE
    assert sv.source_id == SID and sv.page == 1
    assert d["value"]["lat"] == pytest.approx(32 + 45 / 60 + 12 / 3600, abs=1e-6)
    assert d["value"]["lon"] == pytest.approx(-(79 + 58 / 60 + 41 / 3600), abs=1e-6)
    assert d["format"] == "packed_dms" and "model.coords" in d["conversion"]
    assert sv.confidence < loc["confidence"]
    end = out["sections"][0]["end"]["coordinates"]["derived_coordinates"]
    assert end["value"] == {"lat": 32.655, "lon": -79.94} and end["format"] == "decimal"
    assert "derived_coordinates" not in out["surfaces"][1]["location"]   # "near Mount Pleasant"


def test_scope_refuses_new_section_values_outside_the_record(env):
    res = json.loads(json.dumps(RESULT))
    res["contours"][0]["figure"]["page"] = 9
    scopes = {SID: {"pdf_pages": [1, 5], "note": "one paper of a volume"}}
    with pytest.raises(ingest.IngestError, match="contours\\[0\\].figure"):
        env(res, scopes=scopes)


def test_plan_verify_includes_every_subsurface_value():
    paths = ingest.verify_sample(RESULT, fraction=0.1)
    sub = [p for p, _ in schema.iter_values(RESULT)
           if p.split("[", 1)[0] in ("surfaces", "contours", "sections") or
           p.endswith((".datum", ".depth_reference"))]
    assert sub and set(sub) <= set(paths)
    assert paths == ingest.verify_sample(RESULT, fraction=0.1)


def test_plan_verify_cli_lists_subsurface_paths(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(RESULT))
    assert ingest.main([str(p), "--plan-verify"]) == 0
    plan = json.loads(capsys.readouterr().out)
    got = {c["path"]: c for c in plan["checks"]}
    assert got["contours[0].values[1]"]["value"] == -120
    assert got["sections[0].end.coordinates"]["page"] == 4
    assert "observations[0].depth_reference" in got


def test_verify_verdicts_apply_to_subsurface_values(env):
    checks = [{"path": "surfaces[0].elevation", "verdict": "agree"},
              {"path": "contours[0].values[0]", "verdict": "disagree", "value": -80, "note": "label is -80"},
              {"path": "sections[0].units_along[0].top_elevation", "verdict": "unclear"}]
    _, out, queue = env(verify={"source_id": SID, "checks": checks})
    assert out["surfaces"][0]["elevation"]["verification"] == "agree"
    assert out["contours"][0]["values"][0]["verification"] == "disagree"
    assert out["sections"][0]["units_along"][0]["top_elevation"]["verification"] == "unclear"
    problems = {(i["path"], i["problem"]) for i in queue}
    assert ("contours[0].values[0]", "verify_disagree") in problems
    assert ("sections[0].units_along[0].top_elevation", "verify_unclear") in problems


def test_reingest_does_not_duplicate_subsurface_values(env):
    env()
    _, out, _ = env()
    assert len(out["surfaces"]) == 2 and len(out["contours"]) == 1 and len(out["sections"]) == 1
    assert len(out["contours"][0]["values"]) == 2


def test_legacy_output_without_new_sections_merges(env, tmp_path):
    """An extracted file written before the new sections existed is kept and extended."""
    legacy = {"source_id": SID, "schema_version": 1, "blocks_done": [], "units": [], "structures": [],
              "groundwater": [], "references": [], "observations": [{"kind": "well", "label": {
                  "value": "OLD-1", "source_id": SID, "page": 7, "extraction_method": "llm", "confidence": 0.7,
                  "inferred": False, "locator": None, "quote": "OLD-1", "quote_match": "exact"}}]}
    out_dir = tmp_path / "data" / "extracted"
    out_dir.mkdir(parents=True)
    (out_dir / "ngmdb_77.json").write_text(json.dumps(legacy))
    _, out, _ = env()
    assert out["observations"][0]["label"]["value"] == "OLD-1"
    assert len(out["surfaces"]) == 2


# --- backward compatibility with committed data --------------------------------

FILES = sorted((ROOT / "data" / "extracted").glob("*.json"))


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_committed_extractions_still_load_and_merge(path):
    doc = json.loads(path.read_text())
    sections = {k: doc.get(k, []) for k in ingest.SECTIONS}
    vals = [v for _, v in ingest._walk_values(sections)]
    for v in vals:
        StoredValue.from_dict(v)
    # Re-ingesting keeps every earlier record unchanged when nothing on its pages is re-read.
    for key in ingest.SECTIONS:
        kept = [r for r in (ingest._prune(r, lambda f, v: False) for r in doc.get(key, [])) if r is not None]
        assert kept == doc.get(key, [])
    assert ingest._totals(sections)["stored"] == len(vals)
