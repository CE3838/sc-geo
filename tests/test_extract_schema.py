import copy
import json
from pathlib import Path

from extract import schema

ROOT = Path(__file__).resolve().parent.parent


def v(value, page=1, quote=None, inferred=False, **extra):
    return {"value": value, "page": page, "quote": quote or str(value), "inferred": inferred, **extra}


GOOD = {
    "schema_version": 1,
    "source_id": "ngmdb:10009",
    "packets": ["packet-01"],
    "units": [{
        "map_symbol": v("Qw", quote="Qw  Wando Formation"),
        "name": v("Wando Formation"),
        "rank": v("Formation", inferred=True, quote="Wando Formation"),
        "age": v("late Pleistocene", quote="(late Pleistocene)"),
        "thickness": v("as much as 30 ft", quote="as much as 30 ft thick"),
        "group": "not stated",
    }],
    "observations": [{
        "kind": "auger_hole",
        "label": v("AH-12", page=2),
        "location": v("0.5 mi north of Ladson", page=2),
        "intervals": [{"top": v("0 ft", page=2), "bottom": v("4 ft", page=2, table=True),
                       "description": v("sand, yellowish brown", page=2),
                       "munsell": v("10YR 5/6", page=2), "uscs": "not stated"}],
        "water_level": v("3.2 ft", page=2),
    }],
    "structures": [{"kind": "fault", "name": v("Charleston fault", page=3), "certainty": v("inferred", page=3)}],
    "groundwater": [{"aquifer": v("Floridan aquifer", page=4), "role": v("aquifer", page=4)}],
    "references": [{"citation": v("Cooke, C.W., 1936, Geology of the Coastal Plain of South Carolina", page=5)}],
}


def test_schema_file_is_valid_json_with_defs():
    s = json.loads((ROOT / "extract" / "schema.json").read_text())
    assert s["$defs"]["value"]["required"] == ["value", "page", "quote", "inferred"]


def test_good_document_validates():
    assert schema.validate(GOOD) == []


def test_missing_page_quote_inferred_reported_with_path():
    bad = copy.deepcopy(GOOD)
    del bad["units"][0]["name"]["quote"]
    del bad["observations"][0]["intervals"][0]["top"]["page"]
    errs = schema.validate(bad)
    assert any(e.startswith("units[0].name") for e in errs)
    assert any(e.startswith("observations[0].intervals[0].top") for e in errs)


def test_model_may_not_assign_confidence():
    bad = copy.deepcopy(GOOD)
    bad["units"][0]["name"]["confidence"] = 0.9
    assert any("confidence" in e for e in schema.validate(bad))


def test_page_must_be_positive_int():
    bad = copy.deepcopy(GOOD)
    bad["units"][0]["name"]["page"] = 0
    assert schema.validate(bad)
    bad["units"][0]["name"]["page"] = "3"
    assert schema.validate(bad)


def test_unknown_kind_and_top_level_keys_rejected():
    bad = copy.deepcopy(GOOD)
    bad["observations"][0]["kind"] = "spaceship"
    bad["extra"] = 1
    errs = schema.validate(bad)
    assert any("kind" in e for e in errs) and any("extra" in e for e in errs)


def test_not_stated_is_the_only_bare_string():
    bad = copy.deepcopy(GOOD)
    bad["units"][0]["group"] = "Cooper Group"
    assert schema.validate(bad)


def test_iter_values_walks_every_value():
    paths = dict(schema.iter_values(GOOD))
    assert "units[0].name" in paths
    assert "observations[0].intervals[0].bottom" in paths
    assert "units[0].group" not in paths  # 'not stated' is not a value
    assert paths["references[0].citation"]["page"] == 5
    assert len(paths) == 17


def test_get_path():
    assert schema.get_path(GOOD, "observations[0].intervals[0].munsell")["value"] == "10YR 5/6"


def test_extract_prompt_names_every_schema_field():
    """The reading model's instructions must stay in step with the schema."""
    prompt = (ROOT / "extract" / "prompts" / "extract.md").read_text()
    s = json.loads((ROOT / "extract" / "schema.json").read_text())
    for name in ("unit", "interval", "observation", "structure", "groundwater"):
        for field in s["$defs"][name]["properties"]:
            assert f"`{field}`" in prompt, f"{name}.{field} not described in prompts/extract.md"
    for kind in s["$defs"]["observation"]["properties"]["kind"]["enum"]:
        assert kind in prompt
    assert "not stated" in prompt and "inferred" in prompt


def test_verify_prompt_matches_ingest_verdicts():
    prompt = (ROOT / "extract" / "prompts" / "verify.md").read_text()
    for verdict in ("agree", "disagree", "unclear"):
        assert f'"verdict": "{verdict}"' in prompt
    assert "--plan-verify" in prompt and "--verify" in prompt
