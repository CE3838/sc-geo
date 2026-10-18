"""Water tests and rock tests (schema sections water_tests, rock_tests) through ingest."""

import copy
import json
from pathlib import Path

import pytest

from extract import ingest, schema
from model.provenance import ExtractionMethod, StoredValue
from model.units import Lexicon

ROOT = Path(__file__).resolve().parent.parent
SID = "ngmdb:78"
RECORD = {"id": SID, "title": "Ground-water quality near Summerville", "year": 1998, "scale": None,
          "publisher": "U.S. Geological Survey", "citation": "C", "kind": "publication", "status": "published"}
PAGES = {
    1: "Table 2. Well characteristics and field properties\n"
       "Well      Lat      Long      Land surface  Screened interval  Date      pH   Specific conductance\n"
       "                             (ft above NGVD 29) (ft below land surface)        (standard units) (uS/cm)\n"
       "DOR-120  330112   0801005   42            15-25          6/10/1997  5.4  112",
    2: "Table 3. Concentrations of major ions, in milligrams per liter\n"
       "Well      Calcium   Chloride   Nitrate\nDOR-120   12.5      <0.5       ND\n"
       "Spring DOR-SP1 at Givhans: chloride 8.1",
    3: "Table 4. Aquifer-test results. Well DOR-120, pumping test, transmissivity 1,200 ft2/d; "
       "storage coefficient 0.0003. Slug test K | to 6 feet per day",
    4: "Table 5. Rock-core tests, core hole CH-2 (Dorchester County). Depths in feet below land surface.\n"
       "Sample  Depth      Rock type   UCS (psi)   Is(50) (MPa)  RQD\n"
       "R-1     102.0-102.6 limestone  1,250       1.4           85 %\n"
       "Unconfined compressive strength by ASTM D7012 method C; specimens 2.0 in. diameter by 4.1 in. long; "
       "failure along a shear plane. Poisson's ratio 0.21. Point load 0.8",
}


def v(value, page, quote, inferred=False, **kw):
    return {"value": value, "page": page, "quote": quote, "inferred": inferred, **kw}


RESULT = {
    "schema_version": 1, "source_id": SID, "packets": ["packet-01"], "reader": "test",
    "units": [], "structures": [], "groundwater": [], "references": [],
    "observations": [{
        "kind": "well",
        "label": v("DOR-120", 1, "DOR-120  330112   0801005", table=True),
        "location": v("lat 330112, long 0801005", 1, "DOR-120  330112   0801005", table=True),
        "elevation": v(42, 1, "0801005   42", units="ft", table=True),
        "datum": v("NGVD 29", 1, "ft above NGVD 29"),
        "depth_reference": v("land surface", 1, "ft below land surface"),
    }],
    "water_tests": [{
        "kind": "well",
        "observation": v("DOR-120", 1, "DOR-120  330112", table=True),
        "date": v("6/10/1997", 1, "15-25          6/10/1997", table=True),
        "top": v("15 ft", 1, "15-25", table=True),
        "bottom": v("25 ft", 1, "15-25", table=True),
        "depth_reference": v("land surface", 1, "ft below land surface"),
        "parameter": v("pH", 1, "pH   Specific conductance", table=True),
        "value": v(5.4, 1, "6/10/1997  5.4", table=True),
        "units": v("standard units", 1, "(standard units)", table=True),
    }, {
        "kind": "well",
        "observation": v("DOR-120", 2, "DOR-120   12.5", table=True),
        "parameter": v("Calcium", 2, "Well      Calcium", table=True),
        "value": v(12.5, 2, "DOR-120   12.5", table=True),
        "units": v("milligrams per liter", 2, "in milligrams per liter", table=True),
    }, {
        "kind": "well",
        "observation": v("DOR-120", 2, "DOR-120   12.5", table=True),
        "parameter": v("Chloride", 2, "Calcium   Chloride", table=True),
        "value": v("<0.5", 2, "12.5      <0.5", table=True),
        "qualifier": v("<", 2, "<0.5", table=True),
        "units": v("milligrams per liter", 2, "in milligrams per liter", table=True),
    }, {
        "kind": "well",
        "observation": v("DOR-120", 2, "DOR-120   12.5", table=True),
        "parameter": v("Nitrate", 2, "Chloride   Nitrate", table=True),
        "value": v("ND", 2, "<0.5       ND", table=True),
    }, {
        "kind": "spring",
        "observation": v("DOR-SP1", 2, "Spring DOR-SP1 at Givhans"),
        "location": v("at Givhans", 2, "DOR-SP1 at Givhans"),
        "parameter": v("chloride", 2, "chloride 8.1"),
        "value": v(8.1, 2, "chloride 8.1"),                       # units missing: review, never guessed
    }, {
        "kind": "well",
        "observation": v("DOR-120", 3, "Well DOR-120, pumping test"),
        "parameter": v("transmissivity", 3, "transmissivity 1,200 ft2/d"),
        "value": v("1,200 ft2/d", 3, "transmissivity 1,200 ft2/d"),
        "method": v("pumping test", 3, "Well DOR-120, pumping test"),
        "source_table": v("Table 4", 3, "Table 4. Aquifer-test results"),
    }, {
        "kind": "well",
        "observation": v("DOR-120", 3, "Well DOR-120, pumping test"),
        "parameter": v("hydraulic conductivity", 3, "Slug test K"),
        "value": v("1 to 6 feet per day", 3, "K | to 6 feet per day", inferred=True, note="'|' read as 1"),
        "method": v("slug test", 3, "Slug test K"),
    }],
    "rock_tests": [{
        "kind": "core",
        "observation": v("CH-2", 4, "core hole CH-2"),
        "location": v("Dorchester County", 4, "CH-2 (Dorchester County)"),
        "sample_id": v("R-1", 4, "R-1     102.0-102.6", table=True),
        "top": v("102.0 ft", 4, "102.0-102.6", table=True),
        "bottom": v("102.6 ft", 4, "102.0-102.6", table=True),
        "depth_reference": v("land surface", 4, "Depths in feet below land surface"),
        "rock_type": v("limestone", 4, "102.0-102.6 limestone", table=True),
        "test_type": v("UCS", 4, "UCS (psi)", table=True),
        "value": v(1250, 4, "limestone  1,250", table=True),
        "units": v("psi", 4, "UCS (psi)", table=True),
        "standard": v("ASTM D7012 method C", 4, "by ASTM D7012 method C"),
        "specimen_dimensions": v("2.0 in. diameter by 4.1 in. long", 4, "specimens 2.0 in. diameter by 4.1 in. long"),
        "failure_mode": v("failure along a shear plane", 4, "failure along a shear plane"),
    }, {
        "kind": "core",
        "observation": v("CH-2", 4, "core hole CH-2"),
        "sample_id": v("R-1", 4, "R-1     102.0-102.6", table=True),
        "test_type": v("RQD", 4, "Is(50) (MPa)  RQD", table=True),
        "value": v("85 %", 4, "1.4           85 %", table=True),
    }, {
        "kind": "core",
        "observation": v("CH-2", 4, "core hole CH-2"),
        "test_type": v("Poisson's ratio", 4, "Poisson's ratio 0.21"),
        "value": v(0.21, 4, "Poisson's ratio 0.21"),
    }, {
        "kind": "core",
        "observation": v("CH-2", 4, "core hole CH-2"),
        "test_type": v("Point load", 4, "Point load 0.8"),
        "value": v(0.8, 4, "Point load 0.8"),                     # units missing: review
        "rock_type": v("granite", 4, "granite core"),             # not on the page
    }],
}


@pytest.fixture
def env(tmp_path):
    text = tmp_path / ".cache" / "text"
    text.mkdir(parents=True)
    (text / "ngmdb_78.json").write_text(json.dumps({"source_id": SID, "files": [
        {"url": "https://pubs.usgs.gov/x/report.pdf", "via": "pubs_usgs", "pages": 4, "first_page": 1}],
        "pages": [{"page": n, "file": 0, "file_page": n, "method": "pdf_text", "text": t, "raw": t}
                  for n, t in PAGES.items()]}))
    pk = tmp_path / ".cache" / "packets" / "ngmdb_78"
    pk.mkdir(parents=True)
    (pk / "index.json").write_text(json.dumps({"source_id": SID, "blocks": ["1", "2", "3", "4"], "packets": [
        {"file": "packet-01.md", "pages": [1, 2, 3, 4], "blocks": ["1", "2", "3", "4"]}]}))
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
        out = json.loads((kw["out_dir"] / "ngmdb_78.json").read_text())
        queue = json.loads((kw["review_dir"] / "queue.json").read_text())["items"]
        return summary, out, queue
    run.out_dir = kw["out_dir"]
    return run


def problems(queue):
    return {(i["path"], i["problem"]) for i in queue}


# --- schema ------------------------------------------------------------------------

def test_result_is_valid():
    assert schema.validate(RESULT) == []


def test_older_results_without_test_sections_still_validate():
    old = {k: v for k, v in RESULT.items() if k not in ("water_tests", "rock_tests")}
    assert schema.validate(old) == []


@pytest.mark.parametrize("section,field,bad,needle", [
    ("water_tests", "kind", "lake", "kind"),
    ("water_tests", "depth_reference", v("below casing", 1, "q"), "depth_reference"),
    ("water_tests", "confidence", v(0.9, 1, "q"), "confidence"),
    ("rock_tests", "kind", "quarry face", "kind"),
    ("rock_tests", "strength_class", v("strong", 4, "q"), "strength_class"),
])
def test_invalid_test_fields(section, field, bad, needle):
    res = copy.deepcopy(RESULT)
    res[section][0][field] = bad
    errs = schema.validate(res)
    assert errs and any(needle in e for e in errs)


def test_parameter_and_test_type_are_required():
    res = copy.deepcopy(RESULT)
    del res["water_tests"][0]["parameter"]
    del res["rock_tests"][0]["test_type"]
    errs = schema.validate(res)
    assert "water_tests[0].parameter: required" in errs and "rock_tests[0].test_type: required" in errs


def test_spring_is_an_observation_kind():
    res = copy.deepcopy(RESULT)
    res["observations"].append({"kind": "spring", "label": v("DOR-SP1", 2, "Spring DOR-SP1")})
    assert schema.validate(res) == []


# --- ingest -------------------------------------------------------------------------

def test_tests_are_stored_with_provenance(env):
    summary, out, _ = env()
    assert len(out["water_tests"]) == 7 and len(out["rock_tests"]) == 4
    w0 = out["water_tests"][0]
    assert w0["kind"] == "well"
    for field in ("observation", "date", "top", "bottom", "depth_reference", "parameter", "value", "units"):
        sv = StoredValue.from_dict(w0[field])
        assert sv.source_id == SID and sv.page == 1 and sv.extraction_method is ExtractionMethod.LLM
        assert 0 < sv.confidence <= 1 and w0[field]["quote"]
    r0 = out["rock_tests"][0]
    assert r0["kind"] == "core" and r0["standard"]["value"] == "ASTM D7012 method C"
    assert r0["specimen_dimensions"]["page"] == 4 and r0["failure_mode"]["quote"] == "failure along a shear plane"
    assert out["summary"]["stored"] == summary["stored"]


def test_tests_are_quote_checked(env):
    summary, out, queue = env()
    assert "rock_type" not in out["rock_tests"][3]
    assert ("rock_tests[3].rock_type", "quote_not_found") in problems(queue)
    assert summary["values"] == summary["stored"] + 1


def test_tests_are_normalized_and_names_flagged_inferred(env):
    _, out, _ = env()
    w = out["water_tests"]
    assert w[0]["parameter"]["normalized"] == {"name": "pH", "category": "field", "inferred": True}
    assert w[0]["parameter"]["value"] == "pH" and w[0]["parameter"]["inferred"] is False   # as printed
    assert w[0]["top"]["normalized"]["min_ft"] == 15.0 and w[0]["bottom"]["normalized"]["max_ft"] == 25.0
    assert w[0]["date"]["normalized"] == "1997-06-10"
    assert w[2]["value"]["normalized"] == {"number": 0.5, "qualifier": "<"}
    assert w[2]["qualifier"]["normalized"] == "<"
    assert w[3]["value"]["normalized"] == {"number": None, "qualifier": "ND"}
    assert w[5]["parameter"]["normalized"]["category"] == "hydraulic"
    assert w[5]["value"]["normalized"]["number"] == 1200.0
    r = out["rock_tests"]
    assert r[0]["test_type"]["normalized"] == {"type": "ucs", "inferred": True}
    assert r[0]["value"]["normalized"]["number"] == 1250.0
    assert r[1]["test_type"]["normalized"]["type"] == "rqd"
    assert r[0]["top"]["normalized"]["min_ft"] == 102.0


def test_missing_units_go_to_review_and_are_never_guessed(env):
    _, out, queue = env()
    got = problems(queue)
    assert ("water_tests[4].value", "missing_units") in got          # spring chloride: no units printed
    assert ("rock_tests[3].value", "missing_units") in got           # point load: no units printed
    assert "units" not in out["water_tests"][4] and "units" not in out["water_tests"][4]["value"]
    # units given in a field, in the value itself, or not needed (pH has units here; Poisson's ratio has none)
    for ok in ("water_tests[0].value", "water_tests[1].value", "water_tests[5].value", "rock_tests[1].value",
               "rock_tests[2].value", "water_tests[3].value"):
        assert (ok, "missing_units") not in got


def test_ocr_pipe_for_a_digit_goes_to_review(env):
    _, out, queue = env()
    assert ("water_tests[6].value", "ocr_digit") in problems(queue)
    assert out["water_tests"][6]["value"]["inferred"] is True


def test_unreadable_value_goes_to_review(env):
    res = copy.deepcopy(RESULT)
    res["water_tests"][1]["value"] = v("trace", 2, "DOR-120   12.5", table=True)
    _, _, queue = env(res)
    assert ("water_tests[1].value", "unclear_value") in problems(queue)


def test_plan_verify_includes_every_test_value():
    paths = ingest.verify_sample(RESULT, fraction=0.0)
    tests = [p for p, _ in schema.iter_values(RESULT) if p.startswith(("water_tests[", "rock_tests["))]
    assert tests and set(tests) <= set(paths)


def test_verify_verdicts_apply_to_test_values(env):
    checks = [{"path": "water_tests[1].value", "verdict": "agree"},
              {"path": "rock_tests[0].value", "verdict": "disagree", "value": 1520, "note": "digits swapped"},
              {"path": "water_tests[6].value", "verdict": "unclear"}]
    _, out, queue = env(verify={"source_id": SID, "checks": checks})
    assert out["water_tests"][1]["value"]["verification"] == "agree"
    assert out["rock_tests"][0]["value"]["verification"] == "disagree"
    got = problems(queue)
    assert ("rock_tests[0].value", "verify_disagree") in got and ("water_tests[6].value", "verify_unclear") in got


def test_reingest_does_not_duplicate_tests(env):
    env()
    _, out, _ = env()
    assert len(out["water_tests"]) == 7 and len(out["rock_tests"]) == 4


def test_tests_count_in_sections():
    assert "water_tests" in ingest.SECTIONS and "rock_tests" in ingest.SECTIONS


# --- prompts --------------------------------------------------------------------------

def test_extract_prompt_names_every_test_field():
    prompt = (ROOT / "extract" / "prompts" / "extract.md").read_text()
    s = json.loads((ROOT / "extract" / "schema.json").read_text())
    for name in ("water_test", "rock_test"):
        for field in s["$defs"][name]["properties"]:
            assert f"`{field}`" in prompt, f"{name}.{field} not described in prompts/extract.md"
    for section in ("water_tests", "rock_tests"):
        assert f"**{section}**" in prompt
    for word in ("D7012", "D2938", "D5731", "D3967", "D4644", "legend", '"|"', "ND", "spring"):
        assert word in prompt


def test_verify_prompt_covers_test_values():
    prompt = (ROOT / "extract" / "prompts" / "verify.md").read_text()
    for word in ("water_tests", "rock_tests", "units", "qualifier", '"|"'):
        assert word in prompt
