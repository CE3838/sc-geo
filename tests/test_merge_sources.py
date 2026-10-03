import pytest

from merge import score, sources
from model.units import Lexicon

DMU = [
    {"HKey": "01", "MapUnit": "", "Name": "DESCRIPTION OF MAP UNITS", "Age": "", "GeoMat": ""},
    {"HKey": "01-04", "MapUnit": "Qhs", "Name": "Beach and barrier-island sands", "Age": "Holocene", "GeoMat": ""},
    {"HKey": "01-10", "MapUnit": "", "Name": "Wando Formation", "Age": "late Pleistocene, between 70 and 130 ka",
     "GeoMat": ""},
    {"HKey": "01-10-02", "MapUnit": "Qws", "Name": "Barrier-island sand facies", "Age": "late Pleistocene",
     "GeoMat": "Coastal zone sediment", "Descr": "Sand, light-gray, well sorted. " * 40},
    {"HKey": "01-13", "MapUnit": "", "Name": "Daniel Island beds (informal)", "Age": "early Pleistocene"},
    {"HKey": "01-13-01", "MapUnit": "Qdi", "Name": "Clayey sand and clay facies", "Age": "early Pleistocene"},
]
GEMS_DMU = [  # GeMS field names
    {"HierarchyKey": "3", "MapUnit": "", "Name": "Sediments Beneath the Holocene Terrace", "Age": ""},
    {"HierarchyKey": "3-1", "MapUnit": "QHabf", "Name": "Beach sands", "FullName": "Beach sands beneath the Holocene terrace",
     "Age": "Holocene", "GeoMaterial": "Coastal zone sediment", "Description": "Quartz sand"},
]
SOURCE = {"id": "ngmdb:100396", "title": "Surficial geologic map of the Charleston region", "scale": 100000,
          "year": 2014, "citation": "Weems and others, 2014"}


def test_gems_units_attach_facies_to_formations():
    units = sources.gems_units(DMU)
    assert set(units) == {"Qhs", "Qws", "Qdi"}
    qws = units["Qws"]
    assert qws["name"] == "Barrier-island sand facies"
    assert qws["formation"] == "Wando Formation"
    assert qws["unit_name"] == "Wando Formation, barrier-island sand facies"
    assert qws["age"] == "late Pleistocene"
    assert qws["geomaterial"] == "Coastal zone sediment"
    assert len(qws["description"]) <= 501
    assert units["Qhs"]["formation"] is None and units["Qhs"]["unit_name"] == "Beach and barrier-island sands"
    assert units["Qdi"]["formation"] == "Daniel Island beds (informal)"


def test_gems_units_with_standard_field_names():
    u = sources.gems_units(GEMS_DMU)["QHabf"]
    assert u["full_name"] == "Beach sands beneath the Holocene terrace"
    assert u["description"] == "Quartz sand"
    assert u["formation"] is None


def test_unit_feature_schema_and_provenance():
    units = sources.gems_units(DMU)
    poly = {"type": "Polygon", "coordinates": [[[-80, 32.7], [-80, 32.8], [-79.9, 32.8], [-80, 32.7]]]}
    f = sources.unit_feature(poly, {"MapUnit": "Qws", "IdeConf": "certain", "MUPs_ID": "MUP7"}, units, SOURCE)
    p = f["properties"]
    assert p["source"] == "ngmdb:100396" and p["scale"] == 100000 and p["year"] == 2014
    assert p["map_unit"] == "Qws" and p["formation"] == "Wando Formation"
    assert p["identity_confidence"] == "certain"
    assert p["locator"] == "MapUnitPolys_ID=MUP7"
    assert p["extraction_method"] == "gis_import" and p["confidence"] == 1.0
    assert p["age_ma"] == [0.0117, 0.129]
    assert p["layer"] == "surficial"
    assert p["derived_inferred"] is True  # age_ma and layer are derived


def test_unknown_map_unit_is_kept_with_symbol_only():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
    p = sources.unit_feature(poly, {"MapUnit": "Xyz"}, {}, SOURCE)["properties"]
    assert p["map_unit"] == "Xyz" and p["unit_name"] == "Xyz"


def test_facies_agree_with_their_formation_elsewhere():
    lex = Lexicon([{"name": "Wando", "status": "current", "replaced_by": None, "age": "late Pleistocene"}])
    units = sources.gems_units(DMU)
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
    facies = sources.unit_feature(poly, {"MapUnit": "Qws"}, units, SOURCE)["properties"]
    sgmc = sources.sgmc_feature({"type": "Polygon", "coordinates": poly["coordinates"]},
                                {"name": "Wando Formation", "age_min": "Phanerozoic - Cenozoic - Quaternary - Pleistocene",
                                 "age_max": "Phanerozoic - Cenozoic - Quaternary - Pleistocene", "unit": "Qw;1",
                                 "lith": "Unconsolidated, undifferentiated", "major": "Clay, Sand", "ref_id": "SC002",
                                 "unit_age": "Pleistocene", "locator": "OBJECTID=1; UNIT_LINK=SCQw;1",
                                 "source_id": "usgs-sgmc:SC002"})["properties"]
    assert sgmc["scale"] == 500000 and sgmc["layer"] == "surficial" and sgmc["age"] == "Pleistocene"
    c = score.confidence(facies, [(sgmc, 1.0)], lex)
    assert c["agreement"] == 1.0
    assert c["research_support"] is True


@pytest.mark.parametrize("attrs,unit", [
    ({"MapUnit": "nm"}, {"map_unit": "nm", "name": "not mapped", "unit_name": "not mapped", "age": "Unknown",
                         "geomaterial": "Unmapped area"}),
    ({"MapUnit": "GA"}, {"map_unit": "GA", "name": "Portions of Georgia not mapped", "unit_name": "Georgia",
                         "age": "Not Mapped", "geomaterial": None}),
])
def test_unmapped_areas_are_dropped(attrs, unit):
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
    assert sources.unit_feature(poly, attrs, {attrs["MapUnit"]: unit}, SOURCE) is None


def test_shapefile_field_names_cut_to_ten_characters():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
    p = sources.unit_feature(poly, {"MapUnit": "Qws", "IdentityCo": "questionable", "MapUnitPol": "MUP9"},
                             sources.gems_units(DMU), SOURCE)["properties"]
    assert p["identity_confidence"] == "questionable" and p["locator"] == "MapUnitPolys_ID=MUP9"
