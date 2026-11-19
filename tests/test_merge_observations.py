import json

import pytest

pytest.importorskip("shapely")

from merge import observations as ob  # noqa: E402
from model.units import Lexicon  # noqa: E402

LEX = Lexicon([
    {"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"},
    {"name": "Ladson", "status": "current", "replaced_by": None, "age": "early Pleistocene"},
    {"name": "Cooper", "status": "current", "replaced_by": None, "age": "Eocene"},
])
CATALOG = [{"id": "doc:a", "bbox": [-80.0, 32.5, -79.5, 33.0], "citation": "Author, 2001, Report"}]


def sv(value, page=4, inferred=False, **extra):
    return {"value": value, "source_id": "doc:a", "page": page, "extraction_method": "llm", "confidence": 0.8,
            "inferred": inferred, "locator": None, "quote": str(value), **extra}


def derived(lat, lon, inferred=True):
    return {"value": {"lat": lat, "lon": lon}, "source_id": "doc:a", "page": 4, "extraction_method": "inference",
            "confidence": 0.7, "inferred": inferred, "locator": None, "format": "dms", "datum": None,
            "approximate": False, "assumptions": [], "conversion": "model.coords"}


def depth(ft, page=5):
    return sv(ft, page, normalized={"min_ft": ft, "max_ft": ft, "unit": "ft", "approximate": False})


def obs(label, lat=None, lon=None, text=None, intervals=(), kind="boring", loc_inferred=False):
    loc = sv(text or f"lat {lat}, long {lon}", inferred=loc_inferred)
    if lat is not None:
        loc["derived_coordinates"] = derived(lat, lon)
    return {"kind": kind, "label": sv(label), "location": loc, "intervals": list(intervals)}


def interval(unit, top=None, page=5):
    out = {"unit": sv(unit, page)}
    if top is not None:
        out["top"] = depth(top, page)
    return out


def square(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def poly(geom, name, canonical, layer="surficial", map_unit="Qw", source="gis:x"):
    return {"type": "Feature", "geometry": geom, "properties": {
        "source": source, "map_unit": map_unit, "name": name, "canonical": canonical, "layer": layer}}


# West half Wando, east half Ladson; contact at lon -79.75. Bedrock Cooper under all of it.
MERGED = {
    "surficial": [poly(square(-80.0, 32.5, -79.75, 33.0), "Wando Formation", "Wando"),
                  poly(square(-79.75, 32.5, -79.5, 33.0), "Ladson Formation", "Ladson", map_unit="Ql")],
    "bedrock": [poly(square(-80.0, 32.5, -79.5, 33.0), "Cooper Group", "Cooper", layer="bedrock", map_unit="Tc")],
}


def doc(*observations):
    return {"source_id": "doc:a", "citation": "Author, 2001, Report", "year": 2001, "observations": list(observations)}


def run(*observations, merged=MERGED):
    recs = ob.points([doc(*observations)], CATALOG)
    return ob.classify(recs, merged, LEX)


def test_points_take_derived_coordinates_and_keep_provenance():
    recs = ob.points([doc(obs("B-1", 32.75, -79.9, intervals=[interval("Wando Formation", 0)]))], CATALOG)
    r = recs[0]
    assert (r["lat"], r["lon"]) == (32.75, -79.9)
    assert r["source_id"] == "doc:a" and r["page"] == 4 and r["label"] == "B-1" and r["kind"] == "boring"
    assert r["location_inferred"] is True  # the converted coordinate is an inference
    assert r["named_unit"]["value"] == "Wando Formation" and r["named_unit"]["page"] == 5
    assert r["named_unit_top_ft"] == 0


def test_points_parse_printed_coordinates_when_there_is_no_derived_value():
    o = obs("B-2", text="lat 32°45'00\" N., long 79°54'00\" W.", intervals=[interval("Wando Formation", 0)])
    r = ob.points([doc(o)], CATALOG)[0]
    assert r["lat"] == pytest.approx(32.75) and r["lon"] == pytest.approx(-79.9)
    assert r["location_inferred"] is True
    assert r["radius_m"] is not None and r["radius_m"] > 0  # from the printed precision (model.coords)


def test_points_skip_observations_without_a_location():
    o = obs("B-3", text="near the bridge")
    assert ob.points([doc(o)], CATALOG) == []


def test_agree_when_the_named_unit_is_the_mapped_unit():
    r = run(obs("B-1", 32.75, -79.9, intervals=[interval("Wando Fm.", 0)]))[0]
    assert r["status"] == "agree"
    assert r["merged"]["surficial"]["canonical"] == "Wando"
    assert r["merged"]["bedrock"]["canonical"] == "Cooper"
    assert r["matched_layer"] == "surficial"


def test_a_named_bedrock_unit_agrees_with_the_bedrock_layer():
    r = run(obs("C-1", 32.75, -79.9, kind="core", intervals=[interval("Cooper Group", 2)]))[0]
    assert r["status"] == "agree" and r["matched_layer"] == "bedrock"


def test_disagree_far_from_any_contact():
    r = run(obs("B-1", 32.75, -79.95, intervals=[interval("Ladson Formation", 0)]))[0]
    assert r["status"] == "disagree"


def test_near_contact_within_the_location_uncertainty():
    # Printed to the minute: about 1.2 km of rounding; the point is ~0.5 km from the contact.
    o = obs("B-1", text="lat 32°45' N., long 79°45.3' W., NAD 83", intervals=[interval("Ladson Formation", 0)])
    r = run(o)[0]
    assert r["radius_m"] > 900
    assert r["status"] == "near_contact"
    assert r["contact_distance_m"] < r["radius_m"]


def test_no_unit_named_at_the_surface():
    rs = run(obs("B-1", 32.75, -79.9, intervals=[interval("Wando Formation", 40)]),  # too deep
             obs("B-2", 32.75, -79.9, intervals=[interval("fill", 0)]),  # informal name
             obs("B-3", 32.75, -79.9))
    assert [r["status"] for r in rs] == ["no_unit_named"] * 3


def test_outcrop_without_depth_names_its_unit():
    r = run(obs("O-1", 32.75, -79.9, kind="outcrop", intervals=[interval("Wando Formation")]))[0]
    assert r["status"] == "agree"


def test_outside_every_polygon():
    r = run(obs("B-1", 34.0, -81.0, intervals=[interval("Wando Formation", 0)]))[0]
    assert r["status"] == "outside" and r["merged"] == {}


def test_informal_mapped_unit_is_not_comparable():
    merged = {"surficial": [poly(square(-80.0, 32.5, -79.5, 33.0), "Tidal marsh deposits", None)], "bedrock": []}
    r = run(obs("B-1", 32.75, -79.9, intervals=[interval("Wando Formation", 0)]), merged=merged)[0]
    assert r["status"] == "not_comparable"


def test_report_summary_counts_every_status_and_records_cite_pages(tmp_path):
    rs = run(obs("B-1", 32.75, -79.9, intervals=[interval("Wando Formation", 0)]),
             obs("B-2", 32.75, -79.95, intervals=[interval("Ladson Formation", 0)]),
             obs("B-3", 34.0, -81.0))
    rep = ob.report(rs)
    assert rep["summary"] == {"agree": 1, "disagree": 1, "near_contact": 0, "no_unit_named": 0,
                              "not_comparable": 0, "outside": 1, "total": 3}
    assert all(r["source_id"] and r["page"] for r in rep["records"])
    path = ob.write(rep, tmp_path / "merged-observations.json")
    assert json.loads(path.read_text())["summary"]["total"] == 3
