import io
import struct
import zipfile

import pytest

from model import gisio

UTM17_NAD83 = ('PROJCS["NAD_1983_UTM_Zone_17N",GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983",'
               'SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
               'PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",500000.0],PARAMETER["False_Northing",0.0],'
               'PARAMETER["Central_Meridian",-81.0],PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",0.0],'
               'UNIT["Meter",1.0]]')
SC_SPCS_FT = ('PROJCS["NAD_1983_StatePlane_South_Carolina_FIPS_3900_Feet_Intl",GEOGCS["GCS_North_American_1983",'
              'DATUM["D_North_American_1983",SPHEROID["GRS_1980",6378137.0,298.257222101]],PRIMEM["Greenwich",0.0],'
              'UNIT["Degree",0.0174532925199433]],PROJECTION["Lambert_Conformal_Conic"],PARAMETER["False_Easting",2000000.0],'
              'PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",-81.0],PARAMETER["Standard_Parallel_1",32.5],'
              'PARAMETER["Standard_Parallel_2",34.83333333333334],PARAMETER["Latitude_Of_Origin",31.83333333333333],'
              'UNIT["Foot",0.3048]]')
GEOG = 'GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983",SPHEROID["GRS_1980",6378137.0,298.257222101]]]'
NAD27 = 'GEOGCS["GCS_North_American_1927",DATUM["D_North_American_1927",SPHEROID["Clarke_1866",6378206.4,294.9786982]]]'


def test_utm_central_meridian_and_round_trip():
    to_ll = gisio.transformer(UTM17_NAD83)
    lng, lat = to_ll(500000.0, 3_500_000.0)
    assert lng == pytest.approx(-81.0, abs=1e-9)
    assert 31.5 < lat < 31.7
    e, n = gisio.utm_forward(-80.5625, 32.3125, -81.0)
    lng2, lat2 = to_ll(e, n)
    assert lng2 == pytest.approx(-80.5625, abs=1e-8) and lat2 == pytest.approx(32.3125, abs=1e-8)


def test_state_plane_feet_origin():
    to_ll = gisio.transformer(SC_SPCS_FT)
    lng, lat = to_ll(2_000_000.0, 0.0)
    assert lng == pytest.approx(-81.0, abs=1e-9) and lat == pytest.approx(31 + 50 / 60, abs=1e-9)


def test_geographic_passthrough_and_unsupported_datum():
    assert gisio.transformer(GEOG)(-80.0, 33.0) == (-80.0, 33.0)
    with pytest.raises(ValueError, match="datum"):
        gisio.transformer(NAD27)


def _shp(polys):
    """Minimal polygon shapefile (+shx not needed by the reader)."""
    records = b""
    for i, rings in enumerate(polys, 1):
        pts = [p for r in rings for p in r]
        parts = []
        k = 0
        for r in rings:
            parts.append(k)
            k += len(r)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        content = struct.pack("<i4d2i", 5, min(xs), min(ys), max(xs), max(ys), len(rings), len(pts))
        content += struct.pack(f"<{len(parts)}i", *parts)
        content += b"".join(struct.pack("<2d", *p) for p in pts)
        records += struct.pack(">2i", i, len(content) // 2) + content
    header = struct.pack(">7i", 9994, 0, 0, 0, 0, 0, (100 + len(records)) // 2)
    header += struct.pack("<2i4d4d", 1000, 5, 0, 0, 0, 0, 0, 0, 0, 0)
    return header + records


def _dbf(fields, rows):
    n = len(rows)
    rec_len = 1 + sum(w for _, w in fields)
    head = struct.pack("<B3BIHH20x", 3, 26, 10, 3, n, 32 + 32 * len(fields) + 1, rec_len)
    for name, w in fields:
        head += struct.pack("<11sc4xBB14x", name.encode(), b"C", w, 0)
    head += b"\r"
    body = b"".join(b" " + b"".join(str(r[i]).ljust(w)[:w].encode("latin-1") for i, (_, w) in enumerate(fields))
                    for r in rows)
    return head + body + b"\x1a"


def test_read_polygon_shapefile_with_hole_and_attributes():
    outer = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]       # clockwise = outer ring
    hole = [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)]           # counterclockwise = hole
    other = [(20, 0), (20, 5), (25, 5), (25, 0), (20, 0)]
    shp = _shp([[outer, hole], [other]])
    dbf = _dbf([("MapUnit", 10), ("Notes", 20)], [("Qw", "Wando here"), ("Qtm", "marsh")])
    feats = list(gisio.read_shapefile(io.BytesIO(shp), io.BytesIO(dbf)))
    assert [f["properties"] for f in feats] == [{"MapUnit": "Qw", "Notes": "Wando here"},
                                                 {"MapUnit": "Qtm", "Notes": "marsh"}]
    g = feats[0]["geometry"]
    assert g["type"] == "Polygon" and len(g["coordinates"]) == 2
    assert feats[1]["geometry"]["coordinates"][0][0] == [20.0, 0.0]


def test_read_zip_layer_reprojects(tmp_path):
    e, n = gisio.utm_forward(-80.6, 32.3, -81.0)
    ring = [(e, n), (e, n + 100), (e + 100, n + 100), (e + 100, n), (e, n)]
    z = tmp_path / "pkg.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("pkg/GeMS_shapefiles/MapUnitPolys.shp", _shp([[ring]]))
        zf.writestr("pkg/GeMS_shapefiles/MapUnitPolys.dbf", _dbf([("MapUnit", 8)], [("Qw",)]))
        zf.writestr("pkg/GeMS_shapefiles/MapUnitPolys.prj", UTM17_NAD83)
        zf.writestr("pkg/GeMS_shapefiles/DescriptionOfMapUnits.csv", "MapUnit,Name,Age\nQw,Wando Formation,late Pleistocene\n")
    with zipfile.ZipFile(z) as zf:
        layer = gisio.zip_layer(zf, "MapUnitPolys")
        feats = list(gisio.read_layer_lonlat(zf, layer))
        table = gisio.zip_csv(zf, "DescriptionOfMapUnits")
    lng, lat = feats[0]["geometry"]["coordinates"][0][0]
    assert lng == pytest.approx(-80.6, abs=1e-7) and lat == pytest.approx(32.3, abs=1e-7)
    assert table == [{"MapUnit": "Qw", "Name": "Wando Formation", "Age": "late Pleistocene"}]
