import pytest

from merge import classes


@pytest.mark.parametrize("age_ma,expected", [
    ([0.0, 0.0117], "Holocene"),
    ([0.0117, 0.129], "late Pleistocene"),
    ([0.129, 0.774], "middle Pleistocene"),
    ([0.774, 2.58], "early Pleistocene"),
    ([0.0117, 2.58], "Pleistocene"),          # spans all three parts: the parent epoch
    ([0.0, 0.129], "late Pleistocene"),       # 'Holocene and late Pleistocene'
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
    assert ids.index("Holocene") < ids.index("late Pleistocene") < ids.index("Cretaceous") < ids.index("Cambrian")
    colors = [c["color"] for c in classes.AGE_CLASSES]
    assert len(set(colors)) == len(colors)


@pytest.mark.parametrize("props,expected", [
    ({"geomaterial": '"Made" or human-engineered land'}, "Made land"),
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
    ({"geomaterial": None, "lith": None, "name": "Artificial fill"}, "Made land"),
    ({"geomaterial": None, "lith": None, "name": "Something"}, "Unknown"),
])
def test_material_class(props, expected):
    assert classes.material_class(props) == expected
