from merge import extracted_units as xu
from model.provenance import StoredValue
from model.units import Lexicon

LEX = Lexicon([
    {"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"},
    {"name": "Ladson", "status": "current", "replaced_by": None, "age": "early Pleistocene"},
    {"name": "Old Wando", "status": "abandoned", "replaced_by": "Wando", "age": "Pleistocene"},
])


def sv(value, source, page=2, confidence=0.8, **extra):
    return {"value": value, "source_id": source, "page": page, "extraction_method": "llm",
            "confidence": confidence, "inferred": False, "locator": None, "quote": str(value), **extra}


def doc(source, scale, year, units):
    return {"source_id": source, "scale": scale, "year": year, "citation": f"cite {source}", "units": units}


def square(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def poly(source, map_unit, name, geom=None, formation=None):
    return {"type": "Feature", "geometry": geom or square(0, 0, 0.1, 0.1),
            "properties": {"source": source, "map_unit": map_unit, "name": name, "formation": formation}}


CATALOG = [
    {"id": "map:a", "bbox": [-0.5, -0.5, 0.5, 0.5]},
    {"id": "map:a2", "bbox": [-0.5, -0.5, 0.5, 0.5]},
    {"id": "map:b", "bbox": [-1, -1, 1, 1]},
    {"id": "map:far", "bbox": [10, 10, 11, 11]},
]


def test_index_keeps_every_field_as_a_stored_value_with_citation():
    d = doc("map:a", 24000, 2001, [{"name": sv("Wando Formation", "map:a"), "age": sv("late Pleistocene", "map:a"),
                                    "lithology": sv("sand and clay", "map:a", page=3), "map_symbol": sv("Qw", "map:a")}])
    entries = xu.index([d], CATALOG, LEX)
    assert len(entries) == 1
    e = entries[0]
    assert e["source_id"] == "map:a" and e["canonical"] == "Wando" and e["symbol"] == "Qw"
    assert e["bbox"] == [-0.5, -0.5, 0.5, 0.5]
    for field in ("name", "age", "lithology"):
        StoredValue.from_dict(e["fields"][field])  # valid provenance
    assert e["fields"]["lithology"]["page"] == 3
    assert e["fields"]["name"]["quote"] == "Wando Formation"


def test_index_skips_units_without_a_name_and_documents_without_a_footprint():
    d1 = doc("map:a", 24000, 2001, [{"age": sv("Holocene", "map:a")}])
    d2 = doc("map:nowhere", 24000, 2001, [{"name": sv("Wando Formation", "map:nowhere")}])
    assert xu.index([d1, d2], CATALOG, LEX) == []


def test_same_named_unit_matches_across_maps_and_is_flagged_inferred():
    d = doc("map:a", 24000, 2001, [{"name": sv("Wando Fm.", "map:a"), "age": sv("late Pleistocene", "map:a")}])
    feats, table = xu.attach([poly("gis:x", "Qw", "Wando Formation")], xu.index([d], CATALOG, LEX), LEX)
    refs = feats[0]["properties"]["extracted"]
    assert len(refs) == 1
    assert refs[0] == {"id": "map:a#units[0]", "by": "name", "value": "Wando", "inferred": True}
    entry = table[refs[0]["id"]]
    assert entry["fields"]["age"]["value"] == "late Pleistocene"
    assert entry["citation"] == "cite map:a"


def test_abandoned_names_follow_their_replacement():
    d = doc("map:a", 24000, 2001, [{"name": sv("Old Wando Formation", "map:a")}])
    feats, table = xu.attach([poly("gis:x", "Qw", "Wando Formation")], xu.index([d], CATALOG, LEX), LEX)
    assert len(feats[0]["properties"]["extracted"]) == 1


def test_symbol_matches_only_the_maps_own_polygons():
    units = [{"name": sv("Phosphate spoil", "map:a"), "map_symbol": sv("ps", "map:a")}]
    entries = xu.index([doc("map:a", 24000, 2001, units)], CATALOG, LEX)
    own, _ = xu.attach([poly("map:a", "ps", "spoil")], entries, LEX)
    other, _ = xu.attach([poly("gis:x", "ps", "spoil")], entries, LEX)
    assert len(own[0]["properties"]["extracted"]) == 1
    assert other[0]["properties"]["extracted"] == []
    assert own[0]["properties"]["extracted"][0] == {"id": "map:a#units[0]", "by": "symbol", "value": "ps",
                                                    "inferred": False}


def test_different_or_informal_names_do_not_match():
    units = [{"name": sv("Ladson Formation", "map:a")}, {"name": sv("Tidal marsh deposits", "map:a")}]
    feats, _ = xu.attach([poly("gis:x", "Qm", "Tidal marsh deposits"), poly("gis:x", "Qw", "Wando Formation")],
                         xu.index([doc("map:a", 24000, 2001, units)], CATALOG, LEX), LEX)
    assert [f["properties"]["extracted"] for f in feats] == [[], []]


def test_footprint_must_touch_the_polygon():
    units = [{"name": sv("Wando Formation", "map:far")}]
    feats, _ = xu.attach([poly("gis:x", "Qw", "Wando Formation")],
                         xu.index([doc("map:far", 24000, 2001, units)], CATALOG, LEX), LEX)
    assert feats[0]["properties"]["extracted"] == []


def test_matches_rank_most_detailed_then_newest_and_table_is_shared():
    a = doc("map:a", 24000, 1990, [{"name": sv("Wando Formation", "map:a")}])
    b = doc("map:b", 100000, 2020, [{"name": sv("Wando Formation", "map:b")}])
    c = doc("map:a2", 24000, 2015, [{"name": sv("Wando Formation", "map:a2", page=9)}])
    feats = [poly("gis:x", "Qw", "Wando Formation"), poly("gis:x", "Qw", "Wando Formation", square(0.2, 0.2, 0.3, 0.3))]
    out, table = xu.attach(feats, xu.index([a, b, c], CATALOG, LEX), LEX)
    refs = out[0]["properties"]["extracted"]
    assert [(table[r["id"]]["scale"], table[r["id"]]["year"]) for r in refs] == [(24000, 2015), (24000, 1990), (100000, 2020)]
    assert out[1]["properties"]["extracted"] == refs
    assert len(table) == 3


def test_attach_does_not_change_the_polygon_or_its_confidence():
    f = poly("gis:x", "Qw", "Wando Formation")
    f["properties"]["conf"] = 0.7
    d = doc("map:a", 24000, 2001, [{"name": sv("Wando Formation", "map:a")}])
    out, _ = xu.attach([f], xu.index([d], CATALOG, LEX), LEX)
    assert out[0]["properties"]["conf"] == 0.7
    assert out[0]["geometry"] == f["geometry"]
    assert "extracted" not in f["properties"]  # input left as it was


def test_load_reads_extracted_documents(tmp_path):
    import json
    (tmp_path / "x.json").write_text(json.dumps(doc("map:a", 24000, 2001, [{"name": sv("Wando Formation", "map:a")}])))
    (tmp_path / "notes.txt").write_text("ignored")
    docs = xu.load(tmp_path)
    assert [d["source_id"] for d in docs] == ["map:a"]
