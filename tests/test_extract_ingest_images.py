"""Values read from page images: schema, locator check, verify requirement, confidence cap, section geometry."""

import json

import pytest

from extract import images, ingest, schema
from model.units import Lexicon

SID = "ngmdb:8"
RECORD = {"id": SID, "title": "Geologic map of a quadrangle", "year": 2005, "scale": 24000,
          "publisher": "South Carolina Geological Survey", "citation": "C", "kind": "publication",
          "status": "published"}
URL = "https://ngmdb.usgs.gov/img2/x/8_1"
PAGE1 = "A A' FEET Vertical Exaggeration is 20 QTu Tc 8-161 sea level DESCRIPTION OF MAP UNITS Tc Cooper Formation"


def v(value, page, quote, inferred=False, **kw):
    return {"value": value, "page": page, "quote": quote, "inferred": inferred, **kw}


def img(tile, box, **kw):
    return {"tile": tile, "box": box, **kw}


def result(sections=(), units=(), surfaces=()):
    return {"schema_version": 1, "source_id": SID, "packets": ["packet-01"], "units": list(units),
            "observations": [], "structures": [], "groundwater": [], "references": [],
            "sections": list(sections), "surfaces": list(surfaces)}


@pytest.fixture
def env(tmp_path):
    cache = tmp_path / ".cache"
    (cache / "text").mkdir(parents=True)
    pdf = cache / "pdfs" / "ngmdb_8" / "01.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 test")
    (cache / "text" / "ngmdb_8.json").write_text(json.dumps({"source_id": SID, "files": [
        {"url": URL, "path": str(pdf), "via": "ngmdb_image", "pages": 2, "first_page": 1}],
        "pages": [{"page": 1, "file": 0, "file_page": 1, "method": "ocr", "text": PAGE1, "raw": PAGE1},
                  {"page": 2, "file": 0, "file_page": 2, "method": "ocr", "text": "Explanation of symbols here",
                   "raw": ""}]}))
    pk = cache / "packets" / "ngmdb_8"
    pk.mkdir(parents=True)
    (pk / "index.json").write_text(json.dumps({"source_id": SID, "blocks": ["1", "2"], "packets": [
        {"file": "packet-01.md", "pages": [1, 2], "blocks": ["1", "2"], "estimated_tokens": 50}]}))
    images.render(SID, [1], dpi=100, grid=(2, 2), cache_dir=cache,
                  renderer=lambda pdf, n, dpi, box, out: out.write_bytes(b"png"),
                  sizer=lambda pdf, n: (612.0, 792.0), native=lambda pdf, n: None)
    manifest = images.load_manifest(SID, cache / "images")
    kw = dict(text_dir=cache / "text", packets_dir=cache / "packets", out_dir=tmp_path / "data" / "extracted",
              review_dir=tmp_path / "data" / "review", done_dir=tmp_path / ".checkpoints" / "extract",
              catalog={SID: RECORD}, lexicon=Lexicon([]))

    class Env:
        pass
    e = Env()
    e.cache, e.manifest = cache, manifest
    e.tile = next(t for t in manifest["tiles"].values() if t["kind"] == "tile" and t["row"] == 2 and t["col"] == 1)

    def run(res, verify=None):
        p = tmp_path / "r.json"
        p.write_text(json.dumps(res))
        vp = None
        if verify is not None:
            vp = tmp_path / "r.verify.json"
            vp.write_text(json.dumps({"source_id": SID, "checks": verify}))
        return ingest.ingest([p], verify_path=vp, **kw)
    e.run = run
    e.out = lambda: json.loads((kw["out_dir"] / "ngmdb_8.json").read_text())
    e.review = lambda: json.loads((kw["review_dir"] / "queue.json").read_text())["items"]
    return e


def _hole(env, depth="45 ft", **image_kw):
    t = env.tile["tile"]
    return {"name": v("A-A'", 1, "A A'"),
            "holes": [{"label": v("8-161", 1, "8-161"),
                       "intervals": [{"bottom": v(depth, 1, "45", units="ft",
                                                  image=img(t, [100, 200, 140, 220], **image_kw))}]}]}


PATH = "sections[0].holes[0].intervals[0].bottom"


# --- schema ----------------------------------------------------------------------------------

def test_schema_accepts_section_geometry_and_image_locators(env):
    t = env.tile["tile"]
    sec = {
        "name": v("A-A'", 1, "A A'"),
        "start": {"label": v("A", 1, "A A'")}, "end": {"label": v("A'", 1, "A A'")},
        "horizontal_scale": v("1:24,000", 1, "1:24,000", image=img(t, [0, 0, 50, 10])),
        "vertical_exaggeration": v("20", 1, "Vertical Exaggeration is 20"),
        "datum": v("sea level", 1, "sea level"),
        "distance_units": v("feet", 1, "FEET", inferred=True),
        "elevation_units": v("feet", 1, "FEET"),
        "contacts": [{"kind": "contact", "unit": v("QTu", 1, "QTu"), "lower_unit": v("Tc", 1, "Tc"),
                      "certainty": v("dashed", 1, "QTu", inferred=True, image=img(t, [5, 5, 30, 20])),
                      "points": [{"distance": v(0, 1, "A", inferred=True, image=img(t, [0, 0, 9, 9])),
                                  "elevation": v(-20, 1, "-20", inferred=True, units="ft",
                                                 image=img(t, [0, 0, 9, 9], unclear=True))}]}],
        "holes": [{"label": v("8-161", 1, "8-161"), "observation": v("8-161", 1, "8-161"),
                   "distance": v("3,500 ft", 1, "8-161", inferred=True, image=img(t, [1, 1, 5, 5])),
                   "elevation": v(120, 1, "120", units="ft", image=img(t, [1, 1, 5, 5])),
                   "total_depth": v("208 ft", 1, "208", image=img(t, [1, 1, 5, 5])),
                   "depth_reference": v("land surface", 1, "8-161", inferred=True),
                   "intervals": [{"top": v("0", 1, "0", image=img(t, [1, 1, 5, 5])),
                                  "bottom": v("45", 1, "45", image=img(t, [1, 1, 5, 5])),
                                  "unit": v("QTu", 1, "QTu")}]}],
    }
    assert schema.validate(result([sec])) == []


@pytest.mark.parametrize("bad", [{"tile": "x", "box": [1, 2, 3]}, {"tile": "x", "box": [1, 2, 3, 4, 5]},
                                 {"tile": "x"}, {"tile": "x", "box": [1, 2, 3, 4], "page": 1},
                                 {"tile": "", "box": [1, 2, 3, 4]}, {"tile": "x", "box": [-1, 2, 3, 4]}])
def test_schema_refuses_bad_image_locators(bad):
    r = result(units=[{"name": v("Tc", 1, "Tc", image=bad)}])
    assert schema.validate(r)


def test_schema_refuses_unknown_contact_kind():
    r = result([{"contacts": [{"kind": "guess", "points": []}]}])
    assert schema.validate(r)


# --- ingest -----------------------------------------------------------------------------------

def test_verified_image_value_is_stored_with_an_image_locator_and_capped_confidence(env):
    summary = env.run(result([_hole(env)]), verify=[{"path": PATH, "verdict": "agree"}])
    assert summary["image"] == 1 and summary["stored"] == 3
    val = env.out()["sections"][0]["holes"][0]["intervals"][0]["bottom"]
    assert val["extraction_method"] == "llm-image" and val["text_method"] == "image"
    assert val["quote"] == "45" and val["quote_match"] == "image" and val["verification"] == "agree"
    r = images.resolve(env.manifest, env.tile["tile"], [100, 200, 140, 220])
    assert val["locator"] == images.locator(URL, r) and val["locator"].startswith(URL + "#page=1&viewrect=")
    assert val["image"] == {"tile": env.tile["tile"], "box": [100, 200, 140, 220], "dpi": 100,
                            "page_px_box": r["page_px_box"], "pt_box": r["pt_box"],
                            "pdf_sha256": env.manifest["files"]["0"]["sha256"]}
    cap = ingest.CONFIG["images"]["confidence"]["max"]
    assert val["confidence"] <= cap
    # a text-checked value from the same page and verdict scores higher
    label = env.out()["sections"][0]["holes"][0]["label"]
    assert label["extraction_method"] == "llm" and label["confidence"] > val["confidence"]
    assert val["normalized"]["min_ft"] == val["normalized"]["max_ft"] == 45.0


def test_image_value_without_a_verify_pass_is_not_stored(env):
    summary = env.run(result([_hole(env)]))
    assert summary["image_not_verified"] == 1
    assert "intervals" not in env.out()["sections"][0]["holes"][0]
    item = next(i for i in env.review() if i["path"] == PATH)
    assert item["problem"] == "image_not_verified" and item["image"]["tile"] == env.tile["tile"]


@pytest.mark.parametrize("tile,box,page", [("p1-100dpi-r9c9", [1, 1, 5, 5], 1),
                                           (None, [0, 0, 99999, 5], 1),
                                           (None, [1, 1, 5, 5], 2)])
def test_image_value_with_a_bad_locator_is_not_stored(env, tile, box, page):
    sec = {"name": v("A-A'", 1, "A A'"),
           "holes": [{"label": v("8-161", 1, "8-161"),
                      "intervals": [{"bottom": v("45 ft", page, "45",
                                                 image=img(tile or env.tile["tile"], box))}]}]}
    env.run(result([sec]), verify=[{"path": PATH, "verdict": "agree"}])
    assert "intervals" not in env.out()["sections"][0]["holes"][0]
    assert next(i for i in env.review() if i["path"] == PATH)["problem"] == "image_locator_invalid"


def test_image_values_need_the_image_manifest(env):
    (env.cache / "images" / "ngmdb_8" / "manifest.json").unlink()
    env.run(result([_hole(env)]), verify=[{"path": PATH, "verdict": "agree"}])
    item = next(i for i in env.review() if i["path"] == PATH)
    assert item["problem"] == "image_locator_invalid" and "python -m extract.images" in item["detail"]


LABEL = "sections[0].holes[0].label"


def _labelled_hole(env, image=True):
    """A drill-hole label read from a tile whose quote ("8-161") is also in the page's text layer."""
    kw = {"image": img(env.tile["tile"], [10, 10, 60, 30])} if image else {}
    return {"name": v("A-A'", 1, "A A'"), "holes": [{"label": v("8-161", 1, "8-161", **kw)}]}


def test_image_value_whose_quote_is_also_in_the_text_layer_is_still_an_image_value(env):
    summary = env.run(result([_labelled_hole(env)]), verify=[{"path": LABEL, "verdict": "agree"}])
    val = env.out()["sections"][0]["holes"][0]["label"]
    assert summary["image"] == 1
    assert val["extraction_method"] == "llm-image" and val["quote_match"] == "image" and val["text_match"] is True
    assert val["text_method"] == "image" and val["verification"] == "agree"
    assert val["locator"].startswith(URL + "#page=1&viewrect=") and val["image"]["tile"] == env.tile["tile"]
    assert val["confidence"] <= ingest.CONFIG["images"]["confidence"]["max"]


@pytest.mark.parametrize("verdict", [None, "disagree", "unclear"])
def test_image_value_in_the_text_layer_still_needs_an_agreeing_verify_pass(env, verdict):
    verify = [{"path": LABEL, "verdict": verdict, "note": "n"}] if verdict else None
    summary = env.run(result([_labelled_hole(env)]), verify=verify)
    assert summary["image_not_verified"] == 1 and summary["image"] == 0
    assert "holes" not in env.out()["sections"][0]
    item = next(i for i in env.review() if i["path"] == LABEL)
    assert item["problem"] == "image_not_verified" and item.get("verdict") == verdict


def test_reingesting_replaces_a_value_stored_before_the_image_gate(env):
    env.run(result([_labelled_hole(env, image=False)]))  # what an earlier ingest stored as "llm"
    assert env.out()["sections"][0]["holes"][0]["label"]["extraction_method"] == "llm"
    env.run(result([_labelled_hole(env)]), verify=[{"path": LABEL, "verdict": "agree"}])
    out = env.out()
    assert len(out["sections"]) == 1 and len(out["sections"][0]["holes"]) == 1
    assert out["sections"][0]["holes"][0]["label"]["extraction_method"] == "llm-image"


def test_unclear_digits_lower_confidence_and_go_to_review(env):
    env.run(result([_hole(env, depth="45-46 ft", unclear=True)]), verify=[{"path": PATH, "verdict": "agree"}])
    val = env.out()["sections"][0]["holes"][0]["intervals"][0]["bottom"]
    clear = images.confidence(ingest.source_weight(RECORD, "sections", ingest.CONFIG, True), "agree", False,
                              False, ingest.CONFIG)
    assert val["confidence"] < clear and val["image"]["unclear"] is True
    assert next(i for i in env.review() if i["path"] == PATH)["problem"] == "image_unclear"


@pytest.mark.parametrize("verdict", ["disagree", "unclear"])
def test_image_value_the_verify_pass_does_not_agree_with_is_held_for_review(env, verdict):
    summary = env.run(result([_hole(env)]), verify=[{"path": PATH, "verdict": verdict, "value": "48 ft",
                                                     "note": "8 not 5"}])
    assert summary["image_not_verified"] == 1 and summary["image"] == 0 and summary["stored"] == 2
    assert "intervals" not in env.out()["sections"][0]["holes"][0]  # not stored as a value
    item = next(i for i in env.review() if i["path"] == PATH)
    assert item["problem"] == "image_not_verified" and item["verdict"] == verdict and item["note"] == "8 not 5"
    assert item["image"]["tile"] == env.tile["tile"] and item["verify"]["value"] == "48 ft"
    assert [i["problem"] for i in env.review() if i["path"] == PATH] == ["image_not_verified"]


def test_summary_counts_held_back_image_values_even_when_none(env):
    summary = env.run(result([_hole(env)]), verify=[{"path": PATH, "verdict": "agree"}])
    assert summary["image_not_verified"] == 0 and summary["image"] == 1


def test_section_geometry_is_always_flagged_inferred(env):
    t = env.tile["tile"]
    sec = {"name": v("A-A'", 1, "A A'"),
           "contacts": [{"kind": "base", "unit": v("QTu", 1, "QTu"),
                         "points": [{"distance": v(0, 1, "A A'"),
                                     "elevation": v(-20, 1, "-20", units="ft", image=img(t, [3, 3, 9, 9]))}]}]}
    checks = [{"path": "sections[0].contacts[0].points[0].distance", "verdict": "agree"},
              {"path": "sections[0].contacts[0].points[0].elevation", "verdict": "agree"}]
    env.run(result([sec]), verify=checks)
    pt = env.out()["sections"][0]["contacts"][0]["points"][0]
    assert pt["distance"]["inferred"] is True and pt["elevation"]["inferred"] is True
    assert env.out()["sections"][0]["contacts"][0]["kind"] == "base"
    assert env.out()["sections"][0]["contacts"][0]["unit"]["inferred"] is False  # a printed label


def test_every_image_value_is_in_the_verify_plan():
    units = [{"name": v(f"Unit {i}", 1, f"Unit {i}")} for i in range(30)]
    units[7]["map_symbol"] = v("Tc", 1, "Tc", image=img("p1-100dpi-r1c1", [1, 1, 5, 5]))
    plan = ingest.verify_sample(result(units=units))
    assert "units[7].map_symbol" in plan


# --- prompts and docs ----------------------------------------------------------------------------

def _read(*parts):
    return ingest.ROOT.joinpath(*parts).read_text()


def test_extract_prompt_covers_image_packets_and_section_geometry():
    prompt = _read("extract", "prompts", "extract.md")
    s = json.loads(_read("extract", "schema.json"))
    assert "## Image packets" in prompt
    for name in ("image_locator", "section_point", "section_contact", "section_hole"):
        for field in s["$defs"][name]["properties"]:
            assert f"`{field}`" in prompt, f"{name}.{field} not described in prompts/extract.md"
    for word in ("drawn and labelled", "legend", "range", "`unclear`", "python -m extract.images", "inferred",
                 "exaggeration", "datum"):
        assert word in prompt, word


def test_verify_prompt_covers_image_values():
    prompt = _read("extract", "prompts", "verify.md")
    for word in ("tile", "`box`", "`unclear`", "re-view", "llm-image", "legend"):
        assert word in prompt, word


def test_docs_cover_image_rereads():
    session = _read("extract", "SESSION.md")
    readme = _read("extract", "README.md")
    for text in (session, readme):
        assert "python -m extract.images" in text and "llm-image" in text and "--images" in text
    assert "## Page images" in readme and "viewrect" in readme and "image_not_verified" in readme
