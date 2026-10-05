import zipfile

import pytest

from merge import scgs
from model import gisio
from model.units import Lexicon
from tests.test_gisio import SC_SPCS_FT, UTM17_NAD27, UTM17_NAD83, _dbf, _shp

ROCKVILLE = {"id": "ngmdb:100343", "title": "Geologic Map of the Rockville Quadrangle", "scale": 24000, "year": 2006,
             "citation": "Rockville, 2006", "bbox": [-80.25, 32.5, -80.125, 32.625]}
AIKEN = {"id": "ngmdb:109533", "title": "Geologic map of the Aiken quadrangle", "scale": 24000, "year": 2006,
         "citation": None, "bbox": [-81.75, 33.5, -81.625, 33.625]}
LEX = Lexicon([{"name": "McBean", "status": "current", "replaced_by": None, "age": "middle Eocene"}])


def _ring_lonlat(w, s, e, n):
    return [(w, s), (w, n), (e, n), (e, s), (w, s)]   # clockwise = outer ring


def _zip(path, member, rings_xy, fields, rows, prj=None):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{member}.shp", _shp([[r] for r in rings_xy]))
        zf.writestr(f"{member}.dbf", _dbf(fields, rows))
        if prj:
            zf.writestr(f"{member}.prj", prj)
    return path


def _utm(ring, a_e2=None):
    if a_e2:
        return [gisio.tm_forward(x, y, -81.0, a=a_e2[0], e2=a_e2[1]) for x, y in ring]
    return [gisio.utm_forward(x, y, -81.0) for x, y in ring]


@pytest.mark.parametrize("fields,want", [
    (["LABEL", "UNIT_NAME", "AGE"], {"unit": "LABEL", "name": "UNIT_NAME", "age": "AGE"}),
    (["Unit", "Name", "IdeConf"], {"unit": "Unit", "name": "Name", "identity": "IdeConf"}),
    (["AREA", "PERIMETER", "ROCKV06_", "GEOLOGY"], {"unit": "GEOLOGY"}),
    (["MapUnit", "Symbol", "Notes"], {"unit": "MapUnit"}),
])
def test_detect_fields_by_name(fields, want):
    rows = [{f: "Qal" for f in fields}]
    got = scgs.detect_fields(rows)
    for k, v in want.items():
        assert got[k] == v
    assert got["unit_inferred"] is False


def test_detect_fields_falls_back_to_label_like_column_and_flags_it():
    rows = [{"AREA": 12.5, "PERIMETER": 3.0, "ID": 1, "XX": lab} for lab in ["Qal", "Tmb", "Qal", "UKs", "water"]]
    got = scgs.detect_fields(rows)
    assert got["unit"] == "XX" and got["unit_inferred"] is True
    with pytest.raises(ValueError, match="AREA"):
        scgs.detect_fields([{"AREA": 1.0, "PERIMETER": 2.0}])


@pytest.mark.parametrize("label,age", [
    ("Qal", "Quaternary"), ("QHfw", "Holocene"), ("Qct", "Quaternary"), ("TQsl", "Tertiary to Quaternary"),
    ("Tmb", "Tertiary"), ("UKs", "Cretaceous"), ("U UKs", "Cretaceous"), ("L UKs", "Cretaceous"), ("Ks", "Cretaceous"),
    ("CZgn", "Cambrian to Neoproterozoic"), ("Cagn", "Cambrian"), ("Dgr", "Devonian"),
    ("am", None), ("Pu", None), ("M", None), ("water", None), ("", None),
])
def test_age_from_map_symbol(label, age):
    assert scgs.label_age(label) == age


def test_scgs_zip_with_names_ages_and_state_plane_feet(tmp_path):
    ft = 1 / 0.3048
    lcc = lambda x, y: tuple(c * ft for c in gisio.lcc_forward(x, y, -81.0, 31 + 50 / 60, 32.5, 34 + 50 / 60,
                                                              609600.0, 0.0))
    rings = [[lcc(*p) for p in _ring_lonlat(-80.24, 32.51, -80.2, 32.55)],
             [lcc(*p) for p in _ring_lonlat(-80.2, 32.51, -80.13, 32.6)],
             [lcc(*p) for p in _ring_lonlat(-80.15, 32.6, -80.13, 32.62)]]
    z = _zip(tmp_path / "rockv06glc_poly.zip", "rockv06glc_poly", rings,
             [("OBJECTID", 4), ("LABEL", 8), ("UNIT_NAME", 30), ("AGE", 20), ("IDENT_CONF", 12)],
             [("1", "Qw", "Wando Formation", "late Pleistocene", "certain"),
              ("2", "Tmb", "McBean formation", "", ""),
              ("3", "nm", "not mapped", "", "")],
             prj=SC_SPCS_FT)
    with zipfile.ZipFile(z) as zf:
        feats, info = scgs.normalize_zip(zf, ROCKVILLE, lex=LEX)
    assert len(feats) == 2                     # 'not mapped' is dropped
    a, b = (f["properties"] for f in feats)
    assert a["source"] == "ngmdb:100343" and a["map_unit"] == "Qw" and a["name"] == "Wando Formation"
    assert a["formation"] == "Wando Formation" and a["age"] == "late Pleistocene" and a["layer"] == "surficial"
    assert a["identity_confidence"] == "certain" and a["inferred_fields"] == []
    assert a["locator"] == "rockv06glc_poly.shp record 1 (OBJECTID=1)"
    assert a["extraction_method"] == "gis_import" and a["scale"] == 24000 and a["year"] == 2006
    # No age in the table: taken from Geolex for the named unit, flagged inferred.
    assert b["age"] == "middle Eocene" and b["inferred_fields"] == ["age"] and b["layer"] == "surficial"
    lng, lat = feats[0]["geometry"]["coordinates"][0][0]
    assert lng == pytest.approx(-80.24, abs=1e-7) and lat == pytest.approx(32.51, abs=1e-7)
    assert info["fields"]["unit"] == "LABEL" and info["projection"].startswith("NAD_1983_StatePlane")
    assert info["read"] == 3 and info["kept"] == 2 and info["notes"] == []


def test_aiken_labels_take_names_from_the_scgs_key_and_ages_from_symbols(tmp_path):
    rings = [_utm(_ring_lonlat(-81.74, 33.51, -81.7, 33.55)), _utm(_ring_lonlat(-81.7, 33.51, -81.63, 33.6))]
    z = _zip(tmp_path / "aiken08glc_poly.zip", "aiken08glc_poly", rings, [("Label", 10)], [("Tdb",), ("UKs",)],
             prj=UTM17_NAD83)
    with zipfile.ZipFile(z) as zf:
        feats, info = scgs.normalize_zip(zf, AIKEN, lex=LEX)
    a, b = (f["properties"] for f in feats)
    assert a["name"] == "Dry Branch formation" and a["age"] == "Tertiary" and a["inferred_fields"] == ["age"]
    assert b["name"] == "Undifferentiated Cretaceous sediments" and b["age"] == "Cretaceous"
    assert b["layer"] == "surficial" and b["inferred_fields"] == ["age", "geomaterial"]  # '... sediments'
    assert info["fields"]["name"] == "scgs_aiken_key.json"
    assert a["name_source"] == "scgs-aiken-key: Sum_Output.xlsx row 42"
    key = scgs.aiken_key()
    assert key["Tdb"]["unit_name"] == "Dry Branch formation" and key["Tdb"]["locator"].startswith("Sum_Output.xlsx")


def test_nad27_and_missing_prj_are_flagged_approximate(tmp_path):
    ring = _ring_lonlat(-80.24, 32.51, -80.2, 32.55)
    z = _zip(tmp_path / "a.zip", "a", [_utm(ring, gisio.CLARKE_1866)], [("UNIT", 6)], [("Qal",)], prj=UTM17_NAD27)
    with zipfile.ZipFile(z) as zf:
        feats, info = scgs.normalize_zip(zf, ROCKVILLE, lex=LEX)
    assert any("NAD27" in n for n in info["notes"])
    assert "position" in feats[0]["properties"]["inferred_fields"]
    z = _zip(tmp_path / "b.zip", "b", [_utm(ring)], [("UNIT", 6)], [("Qal",)])
    with zipfile.ZipFile(z) as zf:
        feats, info = scgs.normalize_zip(zf, ROCKVILLE, lex=LEX)
    assert info["projection"].startswith("guessed: UTM zone 17N")
    lng, lat = feats[0]["geometry"]["coordinates"][0][0]
    assert lng == pytest.approx(-80.24, abs=1e-7) and lat == pytest.approx(32.51, abs=1e-7)
    assert "position" in feats[0]["properties"]["inferred_fields"]


@pytest.mark.parametrize("names,reason", [
    (["x.gdb/a00000001.gdbtable", "x.gdb/gdb"], "file geodatabase"),
    (["rockv/arc.adf", "rockv/pat.adf", "info/arc0000.dat"], "coverage"),
    (["rockv.e00"], "e00"),
    (["readme.txt"], "no shapefile"),
])
def test_packages_without_shapefiles_are_explained(tmp_path, names, reason):
    z = tmp_path / "p.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n in names:
            zf.writestr(n, b"x")
    with zipfile.ZipFile(z) as zf, pytest.raises(ValueError, match=reason):
        scgs.normalize_zip(zf, ROCKVILLE, lex=LEX)


def test_extent_check():
    assert scgs.extent_check([-80.24, 32.51, -80.13, 32.62], ROCKVILLE["bbox"]) == "ok"
    assert scgs.extent_check([-80.3, 32.4, -80.0, 32.7], ROCKVILLE["bbox"]) == "larger than catalog bbox"
    assert scgs.extent_check([-81.0, 33.0, -80.9, 33.1], ROCKVILLE["bbox"]) == "outside catalog bbox"
    assert scgs.extent_check([-81.0, 33.0, -80.9, 33.1], None) == "no catalog bbox"


@pytest.mark.parametrize("name", ["Artificial fill", "Dredge spoil", "Made land", "Landfill", "Disturbed ground"])
def test_artificial_fill_names_are_surficial(name):
    assert scgs._SEDIMENT_NAME.search(name)
