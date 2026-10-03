import pytest

from merge import score
from model.units import Lexicon

LEX = Lexicon([
    {"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"},
    {"name": "Penholoway", "status": "abandoned", "replaced_by": None, "age": "Pleistocene"},
])


def unit(**kw):
    base = {"source": "ngmdb:1", "scale": 24000, "year": 2010, "name": "Wando Formation", "age": "late Pleistocene",
            "identity_confidence": "certain", "geomaterial": "Coastal zone sediment", "lith": None}
    base.update(kw)
    return base


@pytest.mark.parametrize("scale,expected", [
    (24000, 0.95), (62500, 0.9), (100000, 0.85), (250000, 0.7), (500000, 0.55), (1000000, 0.45), (5000000, 0.35),
    (None, 0.35),
])
def test_scale_weight(scale, expected):
    assert score.scale_weight(scale) == expected


@pytest.mark.parametrize("ic,expected", [("certain", 1.0), ("questionable", 0.8), ("", 0.9), (None, 0.9)])
def test_identity_weight(ic, expected):
    assert score.identity_weight(ic) == expected


def test_priority_prefers_finer_scale_then_newer_then_certain():
    a = unit(scale=24000, year=2000)
    b = unit(scale=100000, year=2022)
    c = unit(scale=24000, year=2010)
    d = unit(scale=24000, year=2010, identity_confidence="questionable")
    ranked = sorted([a, b, c, d], key=score.priority)
    assert ranked == [c, d, a, b]


@pytest.mark.parametrize("u,layer", [
    (unit(geomaterial="Coastal zone sediment"), "surficial"),
    (unit(geomaterial="Alluvial sediment, mostly fine-grained"), "surficial"),
    (unit(geomaterial='"Made" or human-engineered land'), "surficial"),
    (unit(geomaterial=None, lith="Unconsolidated, undifferentiated"), "surficial"),
    (unit(geomaterial=None, lith="Igneous, intrusive"), "bedrock"),
    (unit(geomaterial="Granitic rock", lith=None), "bedrock"),
    (unit(geomaterial="Metamorphic rock", lith=None), "bedrock"),
    # GeMS GeoMaterial terms that say 'sedimentary' are rock, not sediment (I-2175 schists).
    (unit(geomaterial="Schist and gneiss, of sedimentary-rock origin", lith=None, age="Late Proterozoic"), "bedrock"),
    (unit(geomaterial="Sedimentary rock", lith=None, age="Late Cretaceous"), "bedrock"),
    (unit(geomaterial="Unconsolidated sediment (inferred from unit name)", age="Cretaceous"), "surficial"),
    (unit(geomaterial=None, lith=None, age="Carboniferous"), "bedrock"),
    (unit(geomaterial=None, lith=None, age="Pleistocene"), "surficial"),
])
def test_layer(u, layer):
    assert score.layer(u) == layer


def test_confidence_rewards_agreement_and_research_support():
    winner = unit()
    agree = [(unit(source="sgmc", scale=500000, name="Wando Fm."), 1.0)]
    disagree = [(unit(source="sgmc", scale=500000, name="Penholoway Formation", age="Pleistocene"), 1.0)]
    alone = score.confidence(winner, [], LEX)
    with_agree = score.confidence(winner, agree, LEX)
    with_disagree = score.confidence(winner, disagree, LEX)
    assert with_disagree["value"] < alone["value"] < with_agree["value"] <= 1.0
    assert with_agree["agreement"] == 1.0 and with_agree["sources"] == 2
    assert with_disagree["agreement"] == 0.0
    assert with_agree["research_support"] is True  # Wando in Geolex, ages overlap
    assert score.confidence(unit(name="Beach sands", age="Holocene"), [], LEX)["research_support"] is False


def test_confidence_agreement_is_area_weighted():
    winner = unit()
    others = [(unit(source="a", name="Wando Fm."), 0.75), (unit(source="b", name="Penholoway Formation"), 0.25)]
    c = score.confidence(winner, others, LEX)
    assert c["agreement"] == pytest.approx(0.75)


def test_alternatives_list_disagreeing_sources_only():
    winner = unit()
    others = [(unit(source="a", name="Wando Fm."), 0.6), (unit(source="b", name="Penholoway Formation"), 0.4)]
    alts = score.alternatives(winner, others, LEX)
    assert [a["source"] for a in alts] == ["b"]
    assert alts[0]["name"] == "Penholoway Formation"
    assert alts[0]["overlap"] == pytest.approx(0.4)


def test_water_is_left_out_of_agreement_and_alternatives():
    winner = unit()
    water = unit(source="sgmc", scale=500000, name="water", age=None, geomaterial=None, lith="Water")
    agree = unit(source="sgmc", scale=500000, name="Wando Fm.")
    c = score.confidence(winner, [(water, 0.5), (agree, 0.5)], LEX)
    assert c["agreement"] == 1.0 and c["sources"] == 2
    assert score.alternatives(winner, [(water, 0.5)], LEX) == []


def test_one_map_counts_once_even_with_several_parts():
    winner = unit()
    a = unit(source="usgs-sgmc", scale=500000, name="Wando Fm.")
    b = unit(source="usgs-sgmc", scale=500000, name="Penholoway Formation")
    c = score.confidence(winner, [(a, 0.5), (b, 0.5)], LEX)
    assert c["sources"] == 2 and c["agreement"] == 0.5
