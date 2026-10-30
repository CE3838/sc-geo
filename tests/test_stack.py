"""model/stack.py: unit-top surfaces kept in geologic-age order so they never cross."""

import math

import pytest

from model import stack, surfaces
from model.units import Lexicon

LEX = Lexicon([
    {"name": "Wando", "status": "current", "replaced_by": None, "age": "Quaternary (late Pleistocene)*",
     "source_id": "usgs-geolex", "locator": "Wando_1"},
    {"name": "Marks Head", "status": "current", "replaced_by": None, "age": "Tertiary*\nMiocene, early*",
     "source_id": "usgs-geolex", "locator": "MarksHead_1"},
    {"name": "Harleyville", "status": "current", "replaced_by": None, "age": "early Tertiary (late Eocene)",
     "source_id": "usgs-geolex", "locator": "Harleyville_1"},
    {"name": "Parkers Ferry", "status": "current", "replaced_by": None, "age": "Tertiary*\nEocene, late*",
     "source_id": "usgs-geolex", "locator": "ParkersFerry_1"},
])
GRID = [(x, y) for x in range(0, 10001, 1000) for y in range(0, 10001, 1000)]


def grid_surface(f, step=2500):
    return surfaces.build([surfaces.Point(x, y, f(x, y), ref=f"{x},{y}") for x in range(0, 10001, step)
                           for y in range(0, 10001, step)], {"max_distance_ft": 20000.0})


def test_order_comes_from_geologic_age_younger_first():
    tops = {"harleyville": grid_surface(lambda x, y: -80.0), "wando": grid_surface(lambda x, y: -5.0),
            "marks head": grid_surface(lambda x, y: -30.0)}
    st = stack.stack(tops, LEX)
    assert [u["unit"] for u in st.order] == ["wando", "marks head", "harleyville"]
    assert st.order[0]["age"]["source_id"] == "usgs-geolex" and st.order[0]["age"]["inferred"] is True
    assert ("wando", "harleyville") in st.constraints and ("harleyville", "wando") not in st.constraints


def test_unknown_ages_and_overlapping_ages_are_reported_not_reordered():
    tops = {"harleyville": grid_surface(lambda x, y: -80.0), "parkers ferry": grid_surface(lambda x, y: -60.0),
            "mystery": grid_surface(lambda x, y: 10.0), "wando": grid_surface(lambda x, y: -5.0)}
    st = stack.stack(tops, LEX)
    assert st.unknown_age == ["mystery"]
    assert {frozenset(p) for p in st.unordered} == {frozenset({"harleyville", "parkers ferry"})}
    est = st.estimate(5000.0, 5000.0)
    assert est["mystery"]["value"] == pytest.approx(10.0) and est["mystery"]["adjusted"] is False
    # Harleyville and Parkers Ferry are both late Eocene: their order is not set by age, so neither moves.
    assert est["parkers ferry"]["adjusted"] is False and est["harleyville"]["adjusted"] is False


def test_explicit_ages_override_the_lexicon():
    tops = {"a": grid_surface(lambda x, y: 0.0), "b": grid_surface(lambda x, y: -10.0)}
    st = stack.stack(tops, None, ages={"a": "Eocene", "b": "Pleistocene"})
    assert [u["unit"] for u in st.order] == ["b", "a"]
    assert st.order[0]["age"]["source_id"] == "given"


def crossing_pair():
    # Wando's top is flat at -10 ft; the Marks Head top rises eastward and crosses it at x = 5000.
    return {"wando": grid_surface(lambda x, y: -10.0), "marks head": grid_surface(lambda x, y: -20.0 + 0.002 * x)}


def test_stacked_surfaces_never_cross():
    tops = crossing_pair()
    st = stack.stack(tops, LEX)
    raw_cross = sum(tops["marks head"].estimate(x, y)["value"] > tops["wando"].estimate(x, y)["value"] for x, y in GRID)
    assert raw_cross > 10
    for x, y in GRID:
        e = st.estimate(x, y)
        assert e["marks head"]["value"] <= e["wando"]["value"] + 1e-9
    c = st.crossings(step_ft=1000.0)
    pair = c["pairs"][("wando", "marks head")]
    assert pair["crossed_before"] > 0 and pair["crossed_after"] == 0 and pair["worst_after_ft"] == 0.0


def test_adjusted_estimates_are_flagged_inferred_with_reason_and_amount():
    st = stack.stack(crossing_pair(), LEX)
    e = st.estimate(9000.0, 5000.0)                  # Marks Head would be 8 ft above Wando here
    mh, w = e["marks head"], e["wando"]
    for u in (mh, w):
        assert u["adjusted"] is True and u["inferred"] is True
        assert u["moved_ft"] == pytest.approx(u["value"] - u["value_unstacked"])
        assert "geologic age" in u["adjustment_reason"]
    assert mh["moved_ft"] < 0 and w["moved_ft"] > 0
    assert mh["value_unstacked"] - w["value_unstacked"] == pytest.approx(8.0, abs=0.5)
    assert mh["value"] == pytest.approx(w["value"])          # pinched to zero thickness
    assert "down" in mh["adjustment_reason"] and "wando" in mh["adjustment_reason"]
    # Away from the crossing nothing moves.
    far = st.estimate(1000.0, 5000.0)
    assert far["marks head"]["adjusted"] is False and far["marks head"]["moved_ft"] == 0.0
    assert far["marks head"]["value"] == far["marks head"]["value_unstacked"]


def test_the_less_certain_surface_moves_more_and_uncertainty_never_shrinks():
    st = stack.stack(crossing_pair(), LEX)
    e = st.estimate(9000.0, 5000.0)
    mh, w = e["marks head"], e["wando"]
    # Weights are inverse variances: the share of the 8-ft overlap each takes follows its uncertainty.
    share = abs(mh["moved_ft"]) / (abs(mh["moved_ft"]) + abs(w["moved_ft"]))
    assert share == pytest.approx(mh["std_unstacked"] ** 2 / (mh["std_unstacked"] ** 2 + w["std_unstacked"] ** 2),
                                  abs=1e-6)
    for u in (mh, w):
        assert u["std"] >= u["std_unstacked"] - 1e-12
        assert u["std"] == pytest.approx(max(mh["std_unstacked"], w["std_unstacked"]))


def test_a_chain_of_three_units_is_reconciled_in_one_step():
    tops = {"wando": grid_surface(lambda x, y: -10.0), "marks head": grid_surface(lambda x, y: -12.0),
            "harleyville": grid_surface(lambda x, y: -30.0 + 0.004 * x)}   # crosses both
    st = stack.stack(tops, LEX)
    for x, y in GRID:
        e = st.estimate(x, y)
        assert e["wando"]["value"] >= e["marks head"]["value"] - 1e-9 >= e["harleyville"]["value"] - 2e-9
    assert all(v["crossed_after"] == 0 for v in st.crossings(step_ft=1000.0)["pairs"].values())


def test_logged_superposition_that_contradicts_age_is_not_enforced():
    tops = crossing_pair()
    st = stack.stack(tops, LEX, superposition={("marks head", "wando"): 4})
    assert st.conflicts and st.conflicts[0]["younger"] == "wando" and st.conflicts[0]["holes_reversed"] == 4
    assert ("wando", "marks head") not in st.constraints
    assert st.estimate(9000.0, 5000.0)["marks head"]["adjusted"] is False


def test_estimates_beyond_the_maximum_distance_are_left_out():
    tops = crossing_pair()
    tops["wando"] = surfaces.build([surfaces.Point(x, y, -10.0) for x in (0, 2500) for y in (0, 2500, 5000)],
                                   {"max_distance_ft": 1500.0})
    st = stack.stack(tops, LEX)
    e = st.estimate(9000.0, 5000.0)
    assert e["wando"]["value"] is None and e["marks head"]["adjusted"] is False


def test_provenance_lists_order_constraints_and_method():
    st = stack.stack(crossing_pair(), LEX)
    p = st.provenance()
    assert p["inferred"] is True and "age" in p["method"]
    assert [u["unit"] for u in p["order"]] == ["wando", "marks head"]
    assert p["constraints"] == [["wando", "marks head"]]
    assert "uncertainty" in p and p["unknown_age"] == [] and p["unordered"] == []
    assert math.isfinite(p["order"][0]["age"]["range_ma"][1])
