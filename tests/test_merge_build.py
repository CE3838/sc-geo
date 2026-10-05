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
    assert ids[:2] == ["ngmdb:1", "ngmdb:100396"] and "ngmdb:2" not in ids
    assert set(ids[2:]) == {e["id"] for e in build.EXTRA_SOURCES} - {"ngmdb:100396"}
    charleston = build.source_list(CATALOG)[1]
    assert charleston["title"].startswith("Surficial") and "sciencebase" in charleston["download"]


def test_normalize_all_downloads_once_and_reports(tmp_path):
    calls = []

    def fetch(url, dest):
        calls.append(url)
        if "gems_download" not in url:
            raise OSError("offline")
        dest.parent.mkdir(parents=True, exist_ok=True)
        return _package(dest)

    feats, report = build.normalize_all(CATALOG, cache=tmp_path, log=lambda *_: None, fetch=fetch)
    assert len(feats) == 1
    p = feats[0]["properties"]
    assert p["source"] == "ngmdb:1" and p["formation"] == "Wando Formation" and p["layer"] == "surficial"
    assert p["identity_confidence"] == "certain"
    assert p["locator"] == "MapUnitPolys_ID=MUP001"
    assert [r["status"] for r in report[:2]] == ["used", "skipped"]
    assert report[1]["reason"].startswith("OSError")
    assert all(r["status"] == "skipped" for r in report[2:])
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
    assert p["age_class"] == "Pleistocene" and p["material_class"] == "Coastal and marine sediment"
    # The legend class is the epoch; the unit table keeps the refined age for the click box.
    assert units["ngmdb:1|Qws"]["age"] == "late Pleistocene" and units["ngmdb:1|Qws"]["age_ma"] == [0.0117, 0.129]
    assert "description" not in p and "citation" not in p
    assert p["conf"] == 0.9 and p["locator"] == "MapUnitPolys_ID=MUP1"
    assert polys[0]["geometry"]["coordinates"][0][0] == [-79.123457, 32.1]
    u = units["ngmdb:1|Qws"]
    assert u["unit_name"] == "Wando Formation, barrier-island sand facies" and u["description"] == "Sand."
    assert u["age_ma"] == [0.0117, 0.129] and u["canonical"] == "Wando"
    assert srcs["ngmdb:1"] == {"title": "Map A", "citation": "A, 2002", "scale": 24000, "year": 2002}


def test_run_writes_the_reference_list(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "OUT", tmp_path)
    monkeypatch.setattr(build, "normalize_all", lambda catalog, log=print, **kw: ([], []))
    monkeypatch.setattr(build, "sgmc_features", lambda: [])
    build.run(normalize_only=True, log=lambda *_: None)
    data = json.loads((tmp_path / "references.json").read_text())
    assert data["provenance"]["source_id"] == "sc-catalog"
    assert any(r["id"] == "ngmdb:10009" and r["scale"] == 24000 for r in data["records"])


FTP = "ftp://ftpdata.dnr.sc.gov/gisdata/glc/"
MORE = [
    {"id": "ngmdb:3", "title": "Geologic map of the Rockville quadrangle", "scale": 24000, "year": 2006,
     "citation": "Rockville, 2006", "bbox": [-80.25, 32.5, -80.125, 32.625],
     "availability": {"gems_download": None, "scgs_ftp": [FTP + "rockv06glc_line.zip", FTP + "rockv06glc_poly.zip"]}},
    {"id": "ngmdb:4", "title": "Has GeMS too", "scale": 24000, "year": 2002, "citation": None,
     "availability": {"gems_download": "https://ngmdb.usgs.gov/ngm-bin/gems_download.pl?id=4",
                      "scgs_ftp": [FTP + "pritc07glc_poly.zip"]}},
    {"id": "ngmdb:5", "title": "Tapestry of Time and Terrain", "scale": 8000000, "year": 2022, "citation": None,
     "availability": {"gems_download": None, "gis_download": "https://ngmdb.usgs.gov/docs/gis/USGS_DS-1150.zip"}},
    {"id": "scgs-draft:BATES", "title": "Geologic Map of the Batesburg and Emory Quadrangles,", "scale": None,
     "year": None, "citation": None, "bbox": None, "status": "draft",
     "availability": {"gems_download": None, "scgs_ftp": [FTP + "bates08glc_poly.zip", FTP + "bates08glc_line.zip"]}},
]


def test_source_list_adds_scgs_ftp_packages_and_explains_skips():
    srcs = {s["id"]: s for s in build.source_list(CATALOG + MORE)}
    assert srcs["ngmdb:3"]["kind"] == "shapefile" and srcs["ngmdb:3"]["downloads"] == [FTP + "rockv06glc_poly.zip"]
    assert srcs["ngmdb:4"]["kind"] == "gems"                       # GeMS wins over the SCGS shapefile
    assert "8,000,000" in srcs["ngmdb:5"]["skip"]                  # continental map, coarser than SGMC
    draft = srcs["scgs-draft:BATES"]
    assert draft["kind"] == "shapefile" and draft["scale"] == 24000 and draft["scale_inferred"] is True
    assert draft["downloads"] == [FTP + "bates08glc_poly.zip"]
    # Explicit extras: Greenville I-2175 (GeMS open-access shapefiles), SCGS quads the catalog
    # did not link to their FTP files, and maps with no readable public GIS, skipped with reasons.
    assert srcs["ngmdb:13044"]["kind"] == "gems" and "sciencebase" in srcs["ngmdb:13044"]["download"]
    assert srcs["ngmdb:77460"]["downloads"] == [FTP + "dale06glc_poly.zip"]
    assert srcs["ngmdb:77446"]["downloads"] == [FTP + "savan07glc_poly.zip"]
    assert "geodatabase" in srcs["ngmdb:108478"]["skip"]
    assert "no public GIS" in srcs["ngmdb:115932"]["skip"] and "no public GIS" in srcs["ngmdb:115933"]["skip"]
    assert all(s.get("skip") or s.get("download") or s.get("downloads") for s in srcs.values())


def _scgs_package(path):
    ring = [gisio.utm_forward(x, y, -81.0) for x, y in
            [(-80.24, 32.51), (-80.24, 32.6), (-80.13, 32.6), (-80.13, 32.51), (-80.24, 32.51)]]
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("rockv06glc_poly.shp", _shp([[ring]]))
        zf.writestr("rockv06glc_poly.dbf", _dbf([("LABEL", 6), ("UNIT_NAME", 20)], [("Qal", "alluvium")]))
        zf.writestr("rockv06glc_poly.prj", UTM17_NAD83)
    return path


def test_normalize_all_reads_scgs_shapefiles_and_skips_without_downloading(tmp_path):
    calls = []

    def fetch(url, dest):
        calls.append((url, dest.name))
        if url.endswith("rockv06glc_poly.zip"):
            return _scgs_package(dest)
        raise OSError("offline")

    cat = [MORE[0], MORE[2]]
    feats, report = build.normalize_all(cat, cache=tmp_path, log=lambda *_: None, fetch=fetch)
    by_id = {r["id"]: r for r in report}
    assert by_id["ngmdb:3"]["status"] == "used" and by_id["ngmdb:3"]["polygons"] == 1
    assert by_id["ngmdb:3"]["files"][0]["fields"]["unit"] == "LABEL"
    assert by_id["ngmdb:3"]["extent_check"] == "ok" and by_id["ngmdb:3"]["format"] == "shapefile"
    assert by_id["ngmdb:5"]["status"] == "skipped" and "8,000,000" in by_id["ngmdb:5"]["reason"]
    assert not any("DS-1150" in u for u, _ in calls)
    # Fetched through its first mirror (HTTPS), so FTP is never needed.
    https = (FTP + "rockv06glc_poly.zip").replace("ftp://", "https://")
    assert (https, "ngmdb_3__rockv06glc_poly.zip") in calls
    assert (FTP + "rockv06glc_poly.zip", "ngmdb_3__rockv06glc_poly.zip") not in calls
    p = feats[0]["properties"]
    assert p["source"] == "ngmdb:3" and p["map_unit"] == "Qal" and p["layer"] == "surficial"
    # Cached: no download, same report details.
    calls.clear()
    feats2, report2 = build.normalize_all(cat, cache=tmp_path, log=lambda *_: None, fetch=fetch)
    assert not any("rockv" in u for u, _ in calls)
    assert {r["id"]: r for r in report2}["ngmdb:3"]["files"] == by_id["ngmdb:3"]["files"]


def test_scdnr_ftp_files_are_tried_over_https_and_http_first():
    url = FTP + "rockv06glc_poly.zip"
    assert build.mirrors(url) == [url.replace("ftp://", "https://"), url.replace("ftp://", "http://"), url]
    other = "https://ngmdb.usgs.gov/x.zip"
    assert build.mirrors(other) == [other]


def test_first_working_mirror_wins(tmp_path):
    import urllib.error

    calls = []

    def fetch(url, dest):
        calls.append(url)
        if url.startswith("https://ftpdata"):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        dest.write_bytes(b"ok")
        return dest

    guarded = build._skip_dead_hosts(fetch)
    guarded(FTP + "rockv06glc_poly.zip", tmp_path / "a.zip")
    assert [u.split(":")[0] for u in calls] == ["https", "http"]  # FTP never needed


def test_unreachable_host_is_not_retried_for_every_source(tmp_path):
    import urllib.error

    calls = []

    def fetch(url, dest):
        calls.append(url)
        if "ftpdata" in url:
            raise urllib.error.URLError(TimeoutError("timed out"))
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    second = {**MORE[0], "id": "ngmdb:6", "availability": {"scgs_ftp": [FTP + "aiken08glc_poly.zip"]}}
    third = {**MORE[0], "id": "ngmdb:9", "availability": {"scgs_ftp": [FTP + "bates09glc_poly.zip"]}}
    gems = [{**CATALOG[0], "id": f"ngmdb:{i}"} for i in (7, 8)]
    _, report = build.normalize_all([MORE[0], second, third] + gems, cache=tmp_path, log=lambda *_: None,
                                    fetch=fetch)
    by_id = {r["id"]: r for r in report}
    # One slow file is not proof the host is down: a host is given up only after failing on two files.
    tried = [u for u in calls if "ftpdata" in u]
    assert {u.rsplit("/", 1)[1] for u in tried} == {"rockv06glc_poly.zip", "aiken08glc_poly.zip"}
    assert "unreachable earlier in this run" in by_id["ngmdb:9"]["reason"]
    # An HTTP error is about one file, not the host: both GeMS sources were tried.
    assert sum("gems_download" in u for u in calls) == 2


def test_scgs_source_outside_its_catalog_extent_is_skipped(tmp_path):
    rec = {**MORE[0], "bbox": [-82.0, 34.0, -81.875, 34.125]}
    _, report = build.normalize_all([rec], cache=tmp_path, log=lambda *_: None,
                                    fetch=lambda url, dest: _scgs_package(dest))
    assert report[0]["status"] == "skipped" and "outside catalog bbox" in report[0]["reason"]
