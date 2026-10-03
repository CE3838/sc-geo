import json
import zipfile

from merge import build
from tests.test_gisio import UTM17_NAD83, _dbf, _shp
from model import gisio

CATALOG = [
    {"id": "ngmdb:1", "title": "Geologic map of A quadrangle", "scale": 24000, "year": 2002, "citation": "A, 2002",
     "availability": {"gems_download": "https://ngmdb.usgs.gov/ngm-bin/gems_download.pl?id=1&pid=1"}},
    {"id": "ngmdb:2", "title": "Report", "scale": None, "year": 1990, "citation": None,
     "availability": {"gems_download": None}},
    {"id": "ngmdb:100396", "title": "Surficial geologic map of the Charleston region", "scale": 100000, "year": 2014,
     "citation": "Weems and others, 2014", "availability": {"gems_download": None}},
]


def _package(path):
    e, n = gisio.utm_forward(-79.95, 32.8, -81.0)
    ring = [(e, n), (e, n + 100), (e + 100, n + 100), (e + 100, n), (e, n)]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("p/GeMS_shapefiles/MapUnitPolys.shp", _shp([[ring]]))
        zf.writestr("p/GeMS_shapefiles/MapUnitPolys.dbf", _dbf([("OBJECTID", 4), ("MapUnit", 8)], [("1", "Qws")]))
        # The NGMDB shapefile export drops IdentityConfidence; the CSV beside it keeps it.
        zf.writestr("p/GeMS_shapefiles/MapUnitPolys.csv",
                    "OBJECTID,MapUnit,IdentityConfidence,MapUnitPolys_ID\n1,Qws,certain,MUP001\n")
        zf.writestr("p/GeMS_shapefiles/MapUnitPolys.prj", UTM17_NAD83)
        zf.writestr("p/GeMS_shapefiles/DescriptionOfMapUnits.csv",
                    "HierarchyKey,MapUnit,Name,Age,GeoMaterial\n"
                    "1,,Wando Formation,late Pleistocene,\n"
                    "1-1,Qws,Barrier-island sand facies,late Pleistocene,Coastal zone sediment\n")
    return path


def test_source_list_uses_gems_downloads_and_extra_sources():
    ids = [s["id"] for s in build.source_list(CATALOG)]
    assert ids == ["ngmdb:1", "ngmdb:100396"]
    charleston = build.source_list(CATALOG)[1]
    assert charleston["title"].startswith("Surficial") and "sciencebase" in charleston["download"]


def test_normalize_all_downloads_once_and_reports(tmp_path):
    calls = []

    def fetch(url, dest):
        calls.append(url)
        if "sciencebase" in url:
            raise OSError("offline")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return _package(dest)

    feats, report = build.normalize_all(CATALOG, cache=tmp_path, log=lambda *_: None, fetch=fetch)
    assert len(feats) == 1
    p = feats[0]["properties"]
    assert p["source"] == "ngmdb:1" and p["formation"] == "Wando Formation" and p["layer"] == "surficial"
    assert p["identity_confidence"] == "certain"
    assert p["locator"] == "MapUnitPolys_ID=MUP001"
    assert [r["status"] for r in report] == ["used", "skipped"]
    assert report[1]["reason"].startswith("OSError")
    # Second run uses the normalized cache: the GeMS package is not downloaded again.
    calls.clear()
    feats2, _ = build.normalize_all(CATALOG[:1], cache=tmp_path, log=lambda *_: None, fetch=fetch)
    assert not any("gems_download" in c for c in calls) and feats2 == json.loads(json.dumps(feats))


def test_split_tables_keeps_polygons_lean_and_tables_complete():
    full = {
        "source": "ngmdb:1", "source_title": "Map A", "citation": "A, 2002", "scale": 24000, "year": 2002,
        "map_unit": "Qws", "name": "Barrier-island sand facies", "full_name": None, "formation": "Wando Formation",
        "unit_name": "Wando Formation, barrier-island sand facies", "age": "late Pleistocene", "age_ma": [0.0117, 0.129],
        "geomaterial": "Coastal zone sediment", "lith": None, "description": "Sand.", "identity_confidence": "certain",
        "source_id": "ngmdb:1", "locator": "MapUnitPolys_ID=MUP1", "extraction_method": "gis_import",
        "confidence": 1.0, "layer": "surficial", "canonical": "Wando", "conf": 0.9, "conf_base": 0.95,
        "agreement": 1.0, "n_sources": 2, "research_support": True, "alternatives": "[]", "derived_inferred": True,
    }
    geom = {"type": "Polygon", "coordinates": [[[-79.1234567891, 32.1], [-79.2, 32.2], [-79.3, 32.1], [-79.1234567891, 32.1]]]}
    polys, units, srcs = build.split_tables([{"type": "Feature", "geometry": geom, "properties": full}])
    p = polys[0]["properties"]
    assert p["unit"] == "ngmdb:1|Qws"
    assert p["age_class"] == "late Pleistocene" and p["material_class"] == "Coastal and marine sediment"
    assert "description" not in p and "citation" not in p
    assert p["conf"] == 0.9 and p["locator"] == "MapUnitPolys_ID=MUP1"
    assert polys[0]["geometry"]["coordinates"][0][0] == [-79.123457, 32.1]
    u = units["ngmdb:1|Qws"]
    assert u["unit_name"] == "Wando Formation, barrier-island sand facies" and u["description"] == "Sand."
    assert u["age_ma"] == [0.0117, 0.129] and u["canonical"] == "Wando"
    assert srcs["ngmdb:1"] == {"title": "Map A", "citation": "A, 2002", "scale": 24000, "year": 2002}
