import pytest

from merge import classes


@pytest.mark.parametrize("age_ma,expected", [
    ([0.0, 0.0117], "Holocene"),
    # The legend has one Pleistocene class; the unit's own age stays in its properties.
    ([0.0117, 0.129], "Pleistocene"),
    ([0.129, 0.774], "Pleistocene"),
    ([0.774, 2.58], "Pleistocene"),
    ([0.0117, 2.58], "Pleistocene"),
    ([0.0, 0.129], "Pleistocene"),            # 'Holocene and late Pleistocene'
    ([0.0, 0.02], "Holocene"),                # mostly Holocene
    ([2.58, 5.333], "Pliocene"),
    ([15.98, 23.03], "Miocene"),
    ([27.82, 33.9], "Oligocene"),
    ([33.9, 56.0], "Eocene"),
    ([66.0, 100.5], "Cretaceous"),
    ([298.9, 358.9], "Carboniferous"),
    ([251.902, 358.9], "Carboniferous"),
    ([485.4, 538.8], "Cambrian"),
    ([538.8, 1000.0], "Neoproterozoic"),
    (None, "Unknown"),
])
def test_age_class(age_ma, expected):
    assert classes.age_class(age_ma) == expected


def test_age_classes_have_distinct_colors_in_order():
    ids = [c["id"] for c in classes.AGE_CLASSES]
    assert ids.index("Holocene") < ids.index("Pleistocene") < ids.index("Cretaceous") < ids.index("Cambrian")
    assert not {"late Pleistocene", "middle Pleistocene", "early Pleistocene"} & set(ids)
    colors = [c["color"] for c in classes.AGE_CLASSES]
    assert len(set(colors)) == len(colors)


@pytest.mark.parametrize("props,expected", [
    ({"geomaterial": '"Made" or human-engineered land'}, "Artificial fill"),
    ({"geomaterial": "Water or ice"}, "Water"),
    ({"geomaterial": "Peat and muck"}, "Marsh and peat"),
    ({"geomaterial": "Eolian sediment"}, "Eolian sand"),
    ({"geomaterial": "Coastal zone sediment, mostly fine-grained"}, "Coastal and marine sediment"),
    ({"geomaterial": "Marine sediment, mostly coarse-grained"}, "Coastal and marine sediment"),
    ({"geomaterial": "Alluvial sediment"}, "Alluvium"),
    ({"geomaterial": "Clastic sediment"}, "Other sediment"),
    ({"geomaterial": "Medium and high-grade regional metamorphic rock"}, "Metamorphic rock"),
    ({"geomaterial": "Coarse-grained, felsic-composition intrusive igneous rock"}, "Igneous rock"),
    ({"geomaterial": None, "lith": "Unconsolidated, undifferentiated", "name": "Wando Formation"}, "Other sediment"),
    ({"geomaterial": None, "lith": "Metamorphic, gneiss"}, "Metamorphic rock"),
    ({"geomaterial": None, "lith": "Igneous, intrusive"}, "Igneous rock"),
    ({"geomaterial": None, "lith": "Sedimentary, clastic"}, "Sedimentary rock"),
    ({"geomaterial": None, "lith": "Water", "name": "water"}, "Water"),
    ({"geomaterial": None, "lith": None, "name": "Tidal-marsh deposits"}, "Marsh and peat"),
    ({"geomaterial": None, "lith": None, "name": "Artificial fill"}, "Artificial fill"),
    ({"geomaterial": None, "lith": None, "name": "Dredge spoil"}, "Artificial fill"),
    ({"geomaterial": None, "lith": None, "name": "Dredged material disposal area"}, "Artificial fill"),
    ({"geomaterial": None, "lith": None, "name": "Landfill"}, "Artificial fill"),
    ({"geomaterial": None, "lith": None, "name": "Made land"}, "Artificial fill"),
    ({"geomaterial": None, "lith": None, "name": "Reclaimed land"}, "Artificial fill"),
    ({"geomaterial": None, "lith": None, "name": "Disturbed ground"}, "Artificial fill"),
    ({"geomaterial": None, "lith": None, "name": "Moved earth"}, "Artificial fill"),
    ({"geomaterial": None, "lith": None, "name": "Mine tailings"}, "Artificial fill"),
    ({"geomaterial": None, "lith": None, "name": "Anthropogenic deposits"}, "Artificial fill"),
    # Human-moved earth wins even when another field names a natural material.
    ({"geomaterial": "Coastal zone sediment, mostly fine-grained", "lith": None, "name": "Fill over marsh"}, "Artificial fill"),
    # Natural deposits that use the word fill are not artificial.
    ({"geomaterial": None, "lith": None, "name": "Valley-fill alluvium"}, "Alluvium"),
    ({"geomaterial": None, "lith": None, "name": "Channel fill deposits"}, "Other sediment"),
    ({"geomaterial": None, "lith": None, "name": "Infilled lagoon, marine sand"}, "Coastal and marine sediment"),
    ({"geomaterial": None, "lith": None, "name": "Something"}, "Unknown"),
])
def test_material_class(props, expected):
    assert classes.material_class(props) == expected


def test_artificial_fill_is_a_material_class_and_made_land_is_gone():
    ids = [c["id"] for c in classes.MATERIAL_CLASSES]
    assert "Artificial fill" in ids and "Made land" not in ids
