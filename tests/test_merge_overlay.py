import json

import pytest

shapely = pytest.importorskip("shapely")
from shapely.geometry import shape  # noqa: E402

from merge import overlay  # noqa: E402
from model.units import Lexicon  # noqa: E402

LEX = Lexicon([
    {"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"},
    {"name": "Penholoway", "status": "abandoned", "replaced_by": None, "age": "early Pleistocene"},
])


def square(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def feat(geom, source, scale, year, name, age="late Pleistocene", formation=None, layer="surficial"):
    return {"type": "Feature", "geometry": geom, "properties": {
        "source": source, "scale": scale, "year": year, "name": name, "unit_name": name, "formation": formation,
        "age": age, "identity_confidence": "certain", "layer": layer, "map_unit": name[:3], "citation": source}}


def test_detailed_map_wins_where_it_exists_and_coarse_map_fills_the_rest():
    coarse = feat(square(0, 0, 0.1, 0.1), "sgmc", 500000, 2017, "Wando Formation")
    fine = feat(square(0, 0, 0.05, 0.1), "quad", 24000, 2010, "Barrier-island sand facies", formation="Wando Formation")
    out = overlay.merge([coarse, fine], LEX, "surficial")
    by_source = {}
    for f in out:
        by_source.setdefault(f["properties"]["source"], []).append(shape(f["geometry"]))
    assert sum(g.area for g in by_source["quad"]) == pytest.approx(0.005)
    assert sum(g.area for g in by_source["sgmc"]) == pytest.approx(0.005)
    # Pieces do not overlap.
    total = sum(shape(f["geometry"]).area for f in out)
    assert total == pytest.approx(0.01)


def test_agreement_alternatives_and_confidence():
    coarse = feat(square(0, 0, 0.1, 0.1), "sgmc", 500000, 2017, "Penholoway Formation", age="early Pleistocene")
    fine = feat(square(0, 0, 0.05, 0.1), "quad", 24000, 2010, "Barrier-island sand facies", formation="Wando Formation")
    out = {f["properties"]["source"]: f["properties"] for f in overlay.merge([coarse, fine], LEX, "surficial")}
    q = out["quad"]
    assert q["agreement"] == 0.0 and q["n_sources"] == 2
    alts = json.loads(q["alternatives"])
    assert alts[0]["source"] == "sgmc" and alts[0]["name"] == "Penholoway Formation"
    assert q["canonical"] == "Wando"
    # The SGMC remainder has no other map underneath.
    assert out["sgmc"]["n_sources"] == 1 and out["sgmc"]["agreement"] is None
    assert 0 < q["conf"] < 1


def test_only_the_requested_layer_is_merged():
    rock = feat(square(0, 0, 1, 1), "sgmc", 500000, 2017, "Winnsboro Granite", age="Permian", layer="bedrock")
    sed = feat(square(0, 0, 1, 1), "quad", 24000, 2010, "Wando Formation")
    assert {f["properties"]["source"] for f in overlay.merge([rock, sed], LEX, "bedrock")} == {"sgmc"}


def test_invalid_geometry_is_repaired():
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    out = overlay.merge([feat(bowtie, "x", 24000, 2000, "Wando Formation")], LEX, "surficial")
    assert out and all(shape(f["geometry"]).is_valid for f in out)
