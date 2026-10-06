import copy
import json
from pathlib import Path

import pytest

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


# --- subsurface: surfaces, contours, sections ---------------------------------

SUB = {
    **copy.deepcopy(GOOD),
    "surfaces": [{
        "surface": v("top of Cooper Marl", page=6, quote="top of the Cooper Marl"),
        "unit": v("Cooper Marl", page=6),
        "boundary": v("top", page=6, quote="top of the Cooper Marl"),
        "elevation": v(-62, page=6, quote="-62", units="ft", table=True),
        "datum": v("NGVD 29", page=6, quote="feet relative to NGVD 29"),
        "location": v("lat 324512, long 0795841", page=6),
        "observation": v("CHN-14", page=6),
        "method": v("measured", page=6, quote="CHN-14", inferred=True),
    }, {
        "surface": v("base of the surficial aquifer", page=7),
        "depth": v("35 ft", page=7, quote="35 ft below land surface"),
        "datum": v("land surface", page=7, quote="below land surface"),
        "boundary": "not stated",
        "method": v("stated", page=7, quote="35 ft below land surface"),
    }],
    "contours": [{
        "kind": "structure",
        "surface": v("top of the Santee Limestone", page=8),
        "unit": v("Santee Limestone", page=8),
        "interval": v("20 ft", page=8, quote="Contour interval 20 feet"),
        "datum": v("sea level", page=8, quote="Datum is sea level"),
        "units": v("feet", page=8, quote="Contour interval 20 feet"),
        "area": v("Charleston County", page=8),
        "values": [v(-100, page=8, quote="-100"), v(-120, page=8, quote="-120", inferred=True)],
        "figure": v("Figure 5", page=8, quote="Figure 5."),
    }],
    "sections": [{
        "name": v("A-A'", page=9),
        "figure": v("Plate 2", page=9),
        "start": {"location": v("Summerville", page=9), "coordinates": "not stated"},
        "end": {"location": v("Folly Beach", page=9), "coordinates": v("32.655, -79.94", page=9)},
        "vertical_exaggeration": v("x 100", page=9, quote="Vertical exaggeration x 100"),
        "datum": v("sea level", page=9),
        "length": v("30 mi", page=9, quote="30 mi"),
        "observations": [v("CHN-14", page=9), v("DOR-37", page=9)],
        "units_along": [{"unit": v("Ashley Formation", page=9), "from_distance": v("0 mi", page=9),
                         "to_distance": v("12 mi", page=9), "top_elevation": v("-40 ft", page=9),
                         "base_elevation": v("-110 ft", page=9, inferred=True)}],
    }],
}
SUB["observations"][0]["datum"] = v("NAVD 88", page=2)
SUB["observations"][0]["depth_reference"] = v("land surface", page=2, quote="depth below land surface")


def test_subsurface_document_validates_and_old_results_still_do():
    assert schema.validate(SUB) == []
    assert schema.validate(GOOD) == []  # the new sections are optional


@pytest.mark.parametrize("path,bad,needle", [
    (("surfaces", 0, "boundary"), v("middle", page=6), "boundary"),
    (("surfaces", 0, "method"), v("guessed", page=6), "method"),
    (("surfaces", 0, "elevation"), v(-62, page=6, units="yards"), "elevation"),
    (("surfaces", 0, "thickness"), v("10 ft", page=6), "thickness"),
    (("contours", 0, "kind"), "gravity", "kind"),
    (("contours", 0, "values"), v(-100, page=8), "values"),
    (("sections", 0, "units_along", 0, "lithology"), v("sand", page=9), "lithology"),
    (("sections", 0, "start", "page"), 9, "start"),
    (("sections", 0, "observations", 0), "CHN-14", "observations[0]"),
    (("observations", 0, "depth_reference"), v("sea level", page=2), "depth_reference"),
])
def test_subsurface_invalid(path, bad, needle):
    doc = copy.deepcopy(SUB)
    node = doc
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = bad
    errs = schema.validate(doc)
    assert errs and any(needle in e for e in errs), errs


def test_contour_kind_is_required():
    doc = copy.deepcopy(SUB)
    del doc["contours"][0]["kind"]
    assert any("contours[0].kind" in e for e in schema.validate(doc))


def test_iter_values_walks_lists_of_values():
    paths = dict(schema.iter_values(SUB))
    assert "contours[0].values[1]" in paths and "sections[0].observations[1]" in paths
    assert "sections[0].start.location" in paths and "sections[0].end.coordinates" in paths
    assert "sections[0].units_along[0].base_elevation" in paths
    assert "sections[0].start.coordinates" not in paths
    assert paths["surfaces[0].elevation"]["value"] == -62


def test_validator_supports_allof():
    s = {"allOf": [{"type": "object", "required": ["a"]}, {"properties": {"a": {"enum": [1, 2]}}}]}
    assert schema.validate({"a": 1}, s) == []
    assert schema.validate({"a": 3}, s) and schema.validate({}, s)


def test_extract_prompt_names_every_subsurface_field():
    prompt = (ROOT / "extract" / "prompts" / "extract.md").read_text()
    s = json.loads((ROOT / "extract" / "schema.json").read_text())
    for name in ("surface", "contour", "section", "section_end", "section_unit"):
        for field in s["$defs"][name]["properties"]:
            assert f"`{field}`" in prompt, f"{name}.{field} not described in prompts/extract.md"
    for section in ("surfaces", "contours", "sections"):
        assert f"**{section}**" in prompt
    for word in ("NGVD29", "NAVD88", "isopach", "structure", "measured", "contour", "interpolated", "stated"):
        assert word in prompt


def test_verify_prompt_covers_subsurface_values():
    prompt = (ROOT / "extract" / "prompts" / "verify.md").read_text()
    for word in ("surfaces", "contours", "sections", "datum"):
        assert word in prompt
