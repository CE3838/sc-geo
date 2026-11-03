import pytest

from model import units


def close(a, b, tol=0.05):
    return a is not None and abs(a - b) <= tol


@pytest.mark.parametrize("text,young,old", [
    ("Holocene", 0.0, 0.0117),
    ("Pleistocene", 0.0117, 2.58),
    ("Late Pleistocene", 0.0117, 0.129),
    ("late Pleistocene", 0.0117, 0.129),
    ("Quaternary", 0.0, 2.58),
    ("Miocene", 5.333, 23.03),
    ("early Oligocene", 27.82, 33.9),
    ("Eocene", 33.9, 56.0),
    ("Late Cretaceous", 66.0, 100.5),
    ("Upper Cretaceous", 66.0, 100.5),
    ("Maastrichtian", 66.0, 72.1),
    ("Carboniferous to Permian", 251.902, 358.9),
    ("Paleozoic to Neoproterozoic", 251.902, 1000.0),
    ("Pleistocene and Holocene", 0.0, 2.58),
    ("Phanerozoic - Cenozoic - Quaternary - Pleistocene", 0.0117, 2.58),
    ("Phanerozoic - Paleozoic - Cambrian - Middle-Cambrian", 497.0, 509.0),
    ("preCambrian-Proterozoic - Neoproterozoic", 538.8, 1000.0),
    ("early Tertiary (early Oligocene)*", 27.82, 33.9),
    ("Late Paleozoic", 251.902, 347.53),
    ("Cambrian", 485.4, 538.8),
])
def test_age_range(text, young, old):
    r = units.age_range(text)
    assert r is not None, text
    assert close(r[0], young, 0.5) and close(r[1], old, 0.5), (text, r)


@pytest.mark.parametrize("text", [None, "", "Undetermined", "unknown"])
def test_age_range_unknown(text):
    assert units.age_range(text) is None


def test_age_overlap():
    assert units.age_overlap((0.0117, 2.58), (0.0, 0.0117)) == 0.0
    assert units.age_overlap((0.0, 2.58), (0.0117, 0.129)) == pytest.approx(1.0)
    assert 0 < units.age_overlap((5.0, 23.0), (2.58, 10.0)) < 1
    assert units.age_overlap(None, (1, 2)) is None


@pytest.mark.parametrize("name,key,rank", [
    ("Wando Formation", "wando", "formation"),
    ("Wando Fm.", "wando", "formation"),
    ("WANDO FORMATION", "wando", "formation"),
    ("Ashley Formation of Cooper Group", "ashley", "formation"),
    ("Ten Mile Hill beds", "ten mile hill", "beds"),
    ("Black Creek/Cusseta/Blufftown Formations", "black creek", "formation"),
    ("Granite - Winnsboro pluton", "winnsboro", "pluton"),
    ("Silver Bluff beds", "silver bluff", "beds"),
    ("Penholoway Formation", "penholoway", "formation"),
    ("Beach sands", None, None),
    ("Barrier-island sand facies", None, None),
    ("Beach and barrier-island sands", None, None),
    ("Fossiliferous shelf-sand facies", None, None),
    ("Mud flat deposits", None, None),
    ("Freshwater marsh and swamp deposits", None, None),
    ("Wando Formation, barrier-island sand facies", "wando", "formation"),
    ("Moved earth", None, None),
    ("water", None, None),
])
def test_name_key(name, key, rank):
    assert units.name_key(name) == (key, rank)


def test_lexicon_resolves_synonyms_and_abandoned_names():
    lex = units.Lexicon([
        {"name": "Battleground", "status": "current", "replaced_by": None, "age": "Neoproterozoic"},
        {"name": "Bessemer", "status": "abandoned", "replaced_by": "Battleground", "age": None},
        {"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"},
    ])
    assert lex.resolve("Bessemer Granite")["name"] == "Battleground"
    assert lex.resolve("Wando Fm.")["name"] == "Wando"
    assert lex.resolve("Beach sands") is None
    assert lex.resolve("Unknown Formation") is None


def test_same_unit_scores():
    lex = units.Lexicon([{"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"}])
    a = {"name": "Wando Formation", "age": "Pleistocene"}
    b = {"name": "Wando Fm.", "age": "late Pleistocene"}
    c = {"name": "Beach sands", "age": "Holocene"}
    d = {"name": "Beach deposits", "age": "Holocene"}
    e = {"name": "Penholoway Formation", "age": "early Pleistocene"}
    assert lex.agreement(a, b) == 1.0          # same named unit
    assert lex.agreement(c, d) == 0.5          # informal units, same age
    assert lex.agreement(a, e) == 0.0          # different named units
    assert lex.agreement(a, c) == 0.0          # named vs informal, ages don't overlap


def test_lexicon_follows_first_of_several_replacements():
    lex = units.Lexicon([
        {"name": "Kings Mountain", "status": "abandoned", "replaced_by": "Battleground and Blacksburg", "age": None},
        {"name": "Battleground", "status": "current", "replaced_by": None, "age": "Neoproterozoic"},
    ])
    assert lex.resolve("Kings Mountain belt")["name"] == "Battleground"


def test_age_range_and_name_key_are_memoized_and_stable():
    from model import units
    units.age_range.cache_clear()
    units.name_key.cache_clear()
    first = (units.age_range("early Tertiary (early Oligocene)"), units.name_key("Wando Fm."))
    again = (units.age_range("early Tertiary (early Oligocene)"), units.name_key("Wando Fm."))
    assert first == again == ((27.82, 33.9), ("wando", "formation"))
    assert units.age_range.cache_info().hits == 1 and units.name_key.cache_info().hits == 1
    assert units.age_range(None) is None and units.name_key(None) == (None, None)


# --- finest age, for ordering stacked surfaces ------------------------------------

@pytest.mark.parametrize("text,young,old", [
    ("Quaternary (late Pleistocene)*", 0.0117, 0.129),
    ("Tertiary*\nMiocene, early*\nBurdigalian", 15.98, 23.03),            # Geolex 'Miocene, early'
    ("Tertiary*\nEocene, late*\nPriabonian*", 33.9, 37.71),
    ("Tertiary\nPliocene, late\nQuaternary*\nPleistocene, early*", 0.774, 3.6),  # spans two periods
    ("Tertiary*\nlate(?) Oligocene to early Miocene*", 15.98, 27.82),
    ("early Tertiary (early Oligocene; Rupelian)", 27.82, 33.9),
    ("Pleistocene", 0.0117, 2.58),
])
def test_finest_age_range_keeps_the_most_specific_intervals(text, young, old):
    r = units.finest_age_range(text)
    assert close(r[0], young, 0.01) and close(r[1], old, 0.01), (text, r)


def test_finest_age_range_unknown():
    assert units.finest_age_range(None) is None and units.finest_age_range("unknown") is None


def test_unit_age_from_the_lexicon_is_inferred_and_cited():
    lex = units.Lexicon([
        {"name": "Marks Head", "status": "current", "replaced_by": None, "age": "Tertiary*\nMiocene, early*",
         "source_id": "usgs-geolex", "locator": "MarksHead_1"},
        {"name": "Old Name", "status": "abandoned", "replaced_by": "Marks Head", "age": "Eocene"},
    ])
    a = units.unit_age("marks head", lex)
    assert a["range_ma"] == pytest.approx((15.98, 23.03)) and a["inferred"] is True
    assert a["source_id"] == "usgs-geolex" and a["locator"] == "MarksHead_1" and a["name"] == "Marks Head"
    assert units.unit_age("Marks Head Formation", lex)["name"] == "Marks Head"
    assert units.unit_age("old name", lex)["name"] == "Marks Head"   # abandoned names follow the replacement
    assert units.unit_age("nowhere", lex) is None
