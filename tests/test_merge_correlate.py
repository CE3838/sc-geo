import json

from merge import correlate
from merge.correlate import ROOT

TABLE = [{
    "name": "Alluvium", "age": "Holocene", "geomaterial": "Alluvial sediment, mostly fine-grained",
    "members": [{"source": "usgs-sgmc", "map_unit": "Qavs"}],
    "basis": {"source": "ngmdb:100396", "map_unit": "Qal"},
    "reason": "valley-floor alluvium; the 1:500,000 map's alluvial valley swamp meets the 1:24,000 map's alluvium",
    "inferred": True,
}]


def feat(source, map_unit, name, age="Quaternary", age_ma=(0.0, 2.58), lith=None, layer="surficial"):
    return {"type": "Feature", "geometry": None, "properties": {
        "source": source, "map_unit": map_unit, "name": name, "unit_name": name, "full_name": None,
        "age": age, "age_ma": list(age_ma), "geomaterial": None, "lith": lith, "layer": layer,
        "inferred_fields": None}}


def test_a_member_takes_the_correlated_name_age_and_material_and_keeps_what_was_mapped():
    f = feat("usgs-sgmc", "Qavs", "Alluvial Valley Swamp", lith="Unconsolidated, undifferentiated")
    out = correlate.apply([f], TABLE)
    p = out[0]["properties"]
    assert (p["name"], p["unit_name"], p["age"]) == ("Alluvium", "Alluvium", "Holocene")
    assert p["age_ma"] == [0.0, 0.0117]
    assert p["geomaterial"] == "Alluvial sediment, mostly fine-grained"
    assert p["map_unit"] == "Qavs"  # the symbol stays as mapped
    assert p["as_mapped"] == {"name": "Alluvial Valley Swamp", "age": "Quaternary", "age_ma": [0.0, 2.58],
                              "geomaterial": None}
    assert p["correlation"]["basis"] == {"source": "ngmdb:100396", "map_unit": "Qal"}
    assert p["correlation"]["inferred"] is True and "valley-floor" in p["correlation"]["reason"]
    assert {"name", "unit_name", "age", "age_ma", "geomaterial"} <= set(p["inferred_fields"])


def test_other_units_are_untouched():
    f = feat("ngmdb:100396", "Qal", "Alluvium", age="Holocene", age_ma=(0.0, 0.0117))
    g = feat("usgs-sgmc", "Qbs", "Beach Sand")
    before = json.dumps([f, g], sort_keys=True)
    assert json.dumps(correlate.apply([f, g], TABLE), sort_keys=True) == before


def test_the_committed_table_is_well_formed():
    table = correlate.load()
    assert table, "config/unit_correlations.json lists at least one correlation"
    seen = set()
    for c in table:
        assert c["name"] and c["reason"] and c["inferred"] is True
        assert c.get("members") or c.get("names")
        assert all(m["source"] and m["map_unit"] for m in c.get("members", []))
        for m in c.get("members", []):
            key = (m["source"], m["map_unit"])
            assert key not in seen, f"{key} is in two correlations"
            seen.add(key)
    assert (ROOT / "config" / "unit_correlations.json").exists()


def test_names_join_on_any_map_and_age_is_kept_when_the_entry_gives_none():
    table = [{"name": "Salt-marsh deposits", "names": ["Saltmarsh deposits", "Tidal-marsh deposits"],
              "members": [], "reason": "spellings of one unit", "inferred": True}]
    f = feat("ngmdb:77444", "QHsm", "Saltmarsh deposits", age="Holocene", age_ma=(0.0, 0.0117))
    g = feat("ngmdb:100396", "Qht", "tidal-marsh deposits", age="Holocene", age_ma=(0.0, 0.0117))
    out = correlate.apply([f, g], table)
    assert [o["properties"]["name"] for o in out] == ["Salt-marsh deposits", "Salt-marsh deposits"]
    assert out[0]["properties"]["age"] == "Holocene" and out[0]["properties"]["age_ma"] == [0.0, 0.0117]
    assert set(out[0]["properties"]["inferred_fields"]) == {"name", "unit_name"}
