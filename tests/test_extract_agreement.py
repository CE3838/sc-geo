"""extract/agreement.py: independent sources that agree on a surface raise each other's confidence."""

import copy
import json

import pytest

from extract import agreement, renormalize
from model import coords

CFG = {"distance_ft": 1000.0, "tolerance_ft": 5.0, "unit_tolerance_ft": {"cooper marl": 8.0},
       "approximate_extra_ft": 1.0, "boost": 0.25, "cap": 0.98}


def xy_to_ll(dx_ft, dy_ft):
    e0, n0 = coords.latlon_to_state_plane(32.78, -79.95)
    return coords.state_plane_to_latlon(e0 + dx_ft, n0 + dy_ft)


def sv(value, sid, conf=0.7, **kw):
    return {"value": value, "source_id": sid, "page": 4, "extraction_method": "llm", "confidence": conf,
            "inferred": False, "locator": None, "quote": f"q {value}", "quote_match": "exact", **kw}


def surface(sid, z, dx=0.0, unit="Cooper Marl", boundary="top", method="measured", conf=0.7, approx=False):
    lat, lon = xy_to_ll(dx, 0.0)
    nav = sv({"min_ft": z, "max_ft": z}, sid, round(conf * 0.8, 3), extraction_method="datum_conversion",
             inferred=True, approximate=approx)
    return {"unit": sv(unit, sid, normalized={"canonical": unit, "in_geolex": True, "inferred": True}),
            "boundary": sv(boundary, sid), "method": sv(method, sid),
            "location": sv("loc", sid, derived_coordinates={"value": {"lat": lat, "lon": lon}}),
            "elevation": sv(z, sid, conf, navd88=nav)}


def doc(sid, *surfaces):
    return {"source_id": sid, "year": 1990, "units": [], "observations": [], "structures": [], "groundwater": [],
            "references": [], "surfaces": list(surfaces)}


def test_measured_and_contour_agreeing_raise_both():
    docs = {"a": doc("ngmdb:1", surface("ngmdb:1", -62.0)),
            "b": doc("ngmdb:2", surface("ngmdb:2", -60.0, dx=300, method="contour", conf=0.55))}
    out, report = agreement.apply(docs, CFG)
    a = out["a"]["surfaces"][0]["elevation"]
    b = out["b"]["surfaces"][0]["elevation"]
    assert a["confidence"] == round(1 - (1 - 0.7) * 0.75, 3)
    assert b["confidence"] == round(1 - (1 - 0.55) * 0.75, 3)
    ag = a["agreement"]
    assert ag["confidence_before"] == 0.7 and ag["k"] == 1
    other = ag["agrees_with"][0]
    assert other["source_id"] == "ngmdb:2" and other["path"] == "surfaces[0].elevation" and other["page"] == 4
    assert other["delta_ft"] == pytest.approx(2.0) and other["distance_ft"] == pytest.approx(300, abs=1)
    # the derived NAVD88 value is raised the same way, from its own confidence
    assert a["navd88"]["confidence"] == round(1 - (1 - 0.56) * 0.75, 3)
    assert report["agreements"] == 1
    assert docs["a"]["surfaces"][0]["elevation"]["confidence"] == 0.7  # inputs untouched


def test_disagreement_is_kept_as_an_alternative_without_a_boost():
    docs = {"a": doc("ngmdb:1", surface("ngmdb:1", -62.0)),
            "b": doc("ngmdb:2", surface("ngmdb:2", -90.0, dx=200, method="contour"))}
    out, report = agreement.apply(docs, CFG)
    a = out["a"]["surfaces"][0]["elevation"]
    assert a["confidence"] == 0.7
    alt = a["agreement"]["disagrees_with"][0]
    assert alt["source_id"] == "ngmdb:2" and alt["delta_ft"] == pytest.approx(-28.0)
    assert out["b"]["surfaces"][0]["elevation"]["agreement"]["disagrees_with"][0]["source_id"] == "ngmdb:1"
    assert report["disagreements"] == 1


@pytest.mark.parametrize("other", [
    dict(dx=5000),                                         # too far apart
    dict(unit="Ashley Formation"),                         # another unit
    dict(boundary="base"),                                 # another boundary
    dict(method="contour", sid="ngmdb:1"),                 # same source is not independent
])
def test_no_pair(other):
    sid = other.pop("sid", "ngmdb:2")
    docs = {"a": doc("ngmdb:1", surface("ngmdb:1", -62.0)), "b": doc(sid, surface(sid, -62.0, **other))}
    out, report = agreement.apply(docs, CFG)
    assert "agreement" not in out["a"]["surfaces"][0]["elevation"] and report["agreements"] == 0


def test_two_contour_maps_alone_do_not_count():
    docs = {"a": doc("ngmdb:1", surface("ngmdb:1", -62.0, method="contour")),
            "b": doc("ngmdb:2", surface("ngmdb:2", -62.0, method="contour"))}
    out, _ = agreement.apply(docs, CFG)
    assert "agreement" not in out["a"]["surfaces"][0]["elevation"]


def test_tolerance_by_unit_and_for_approximate_values():
    base = {**CFG, "unit_tolerance_ft": {}}
    d = {"a": doc("ngmdb:1", surface("ngmdb:1", -62.0)), "b": doc("ngmdb:2", surface("ngmdb:2", -69.0))}
    assert agreement.apply(d, base)[1]["agreements"] == 0           # 7 ft > 5 ft
    assert agreement.apply(d, CFG)[1]["agreements"] == 1            # Cooper Marl: 8 ft
    d = {"a": doc("ngmdb:1", surface("ngmdb:1", -62.0)), "b": doc("ngmdb:2", surface("ngmdb:2", -67.5, approx=True))}
    assert agreement.apply(d, base)[1]["agreements"] == 1           # 5 + 1 ft for an approximate datum


def test_boost_is_bounded_and_grows_with_independent_sources():
    docs = {"a": doc("ngmdb:1", surface("ngmdb:1", -62.0, conf=0.9))}
    for i in range(2, 12):
        docs[str(i)] = doc(f"ngmdb:{i}", surface(f"ngmdb:{i}", -62.0, dx=10 * i, method="contour"))
    out, _ = agreement.apply(docs, CFG)
    a = out["a"]["surfaces"][0]["elevation"]
    assert a["agreement"]["k"] == 10 and a["confidence"] == 0.98
    assert agreement.boosted(0.5, 1, CFG) < agreement.boosted(0.5, 2, CFG) < 1


def test_idempotent_and_reversible():
    docs = {"a": doc("ngmdb:1", surface("ngmdb:1", -62.0)), "b": doc("ngmdb:2", surface("ngmdb:2", -60.0))}
    once, _ = agreement.apply(docs, CFG)
    twice, _ = agreement.apply(once, CFG)
    assert twice == once
    lonely, _ = agreement.apply({"a": once["a"]}, CFG)               # the other source is gone
    assert lonely["a"] == docs["a"]


def test_cli_dry_run_and_write(tmp_path, capsys):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(renormalize.dumps(doc("ngmdb:1", surface("ngmdb:1", -62.0))))
    b.write_text(renormalize.dumps(doc("ngmdb:2", surface("ngmdb:2", -60.0))))
    before = a.read_text()
    assert agreement.main([str(a), str(b)]) == 0
    assert json.loads(capsys.readouterr().out)["agreements"] == 1 and a.read_text() == before
    assert agreement.main([str(a), str(b), "--write"]) == 0
    assert json.loads(a.read_text())["surfaces"][0]["elevation"]["agreement"]["k"] == 1


def test_config_has_the_documented_keys():
    c = agreement.CONFIG
    assert {"distance_ft", "tolerance_ft", "unit_tolerance_ft", "approximate_extra_ft", "boost", "cap"} <= set(c)
    assert 0 < c["boost"] < 1 and c["cap"] < 1


def test_renormalizing_after_agreement_does_not_compound():
    from extract import elevations
    docs = {"a": doc("ngmdb:1", surface("ngmdb:1", -62.0)), "b": doc("ngmdb:2", surface("ngmdb:2", -60.0))}
    once, _ = agreement.apply(docs, CFG)
    redone = copy.deepcopy(once)
    vcfg = {"msl_as_ngvd29_before": 1991, "fallback_ngvd29_to_navd88_ft": None, "approximate_factor": 0.9}
    for d in redone.values():
        # NAVD88 already in the text: elevations rebuilds the navd88 value from the ingest confidence
        d["surfaces"][0]["elevation"]["value"] = f"{d['surfaces'][0]['elevation']['value']} ft NAVD 88"
        elevations.attach_navd88(d, 1990, None, vcfg)
    nav = redone["a"]["surfaces"][0]["elevation"]["navd88"]
    assert nav["confidence"] == round(0.7 * 0.8, 3)   # from the ingest confidence, not the boosted one
    again, _ = agreement.apply(redone, CFG)
    assert again["a"]["surfaces"][0]["elevation"]["confidence"] == once["a"]["surfaces"][0]["elevation"]["confidence"]
    assert again["a"]["surfaces"][0]["elevation"]["navd88"]["confidence"] == round(1 - (1 - 0.56) * 0.75, 3)
