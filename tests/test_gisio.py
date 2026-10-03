import io
import math
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


# --- other datums, ArcInfo .prj files, projection guessing ---------------------

UTM17_NAD27 = ('PROJCS["NAD_1927_UTM_Zone_17N",GEOGCS["GCS_North_American_1927",DATUM["D_North_American_1927",'
               'SPHEROID["Clarke_1866",6378206.4,294.9786982]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
               'PROJECTION["Transverse_Mercator"],PARAMETER["False_Easting",500000.0],PARAMETER["False_Northing",0.0],'
               'PARAMETER["Central_Meridian",-81.0],PARAMETER["Scale_Factor",0.9996],PARAMETER["Latitude_Of_Origin",0.0],'
               'UNIT["Meter",1.0]]')
SC_SPCS_NAD27_SOUTH = ('PROJCS["NAD_1927_StatePlane_South_Carolina_South_FIPS_3902",GEOGCS["GCS_North_American_1927",'
                       'DATUM["D_North_American_1927",SPHEROID["Clarke_1866",6378206.4,294.9786982]],PRIMEM["Greenwich",0.0],'
                       'UNIT["Degree",0.0174532925199433]],PROJECTION["Lambert_Conformal_Conic"],'
                       'PARAMETER["False_Easting",2000000.0],PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",-81.0],'
                       'PARAMETER["Standard_Parallel_1",32.33333333333334],PARAMETER["Standard_Parallel_2",33.66666666666666],'
                       'PARAMETER["Latitude_Of_Origin",31.83333333333333],UNIT["Foot_US",0.3048006096012192]]')
ARCINFO_SP83_FEET = ("Projection    STATEPLANE\nFipszone      3900\nDatum         NAD83\nSpheroid      GRS1980\n"
                     "Units         FEET\nZunits        NO\nParameters\n")
ARCINFO_UTM27 = "Projection    UTM\nZone          17\nDatum         NAD27\nSpheroid      CLARKE1866\nUnits         METERS\nParameters\n"


def _molodensky_nad27(lng, lat):
    """Abridged Molodensky NAD27 -> WGS84 (independent check of the exact geocentric shift)."""
    import math
    a, f = 6378206.4, 1 / 294.9786982
    da, df = 6378137.0 - a, 1 / 298.257222101 - f
    dx, dy, dz = -8.0, 160.0, 176.0
    e2 = f * (2 - f)
    p, l = math.radians(lat), math.radians(lng)
    m = a * (1 - e2) / (1 - e2 * math.sin(p) ** 2) ** 1.5
    n = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    dp = (-dx * math.sin(p) * math.cos(l) - dy * math.sin(p) * math.sin(l) + dz * math.cos(p)
          + (a * df + f * da) * math.sin(2 * p)) / m
    dl = (-dx * math.sin(l) + dy * math.cos(l)) / (n * math.cos(p))
    return lng + math.degrees(dl), lat + math.degrees(dp)


def test_nad27_is_shifted_only_when_approximation_is_allowed():
    with pytest.raises(ValueError, match="datum"):
        gisio.transformer(UTM17_NAD27)
    to_ll = gisio.transformer(UTM17_NAD27, allow_approximate=True)
    assert gisio.datum_note(UTM17_NAD27).startswith("NAD27")
    assert gisio.datum_note(UTM17_NAD83) is None
    # A NAD27 UTM coordinate: invert on Clarke 1866, then shift to NAD83.
    e, n = gisio.tm_forward(-80.0, 32.8, -81.0, a=gisio.CLARKE_1866[0], e2=gisio.CLARKE_1866[1])
    lng, lat = to_ll(e, n)
    want = _molodensky_nad27(-80.0, 32.8)
    assert lng == pytest.approx(want[0], abs=1e-5) and lat == pytest.approx(want[1], abs=1e-5)  # about 1 m
    shift_m = math.hypot((lng + 80.0) * 93_600, (lat - 32.8) * 110_900)
    assert 10 < shift_m < 60


def test_nad27_state_plane_and_geographic():
    to_ll = gisio.transformer(SC_SPCS_NAD27_SOUTH, allow_approximate=True)
    lng, lat = to_ll(2_000_000.0, 0.0)  # projection origin, before the datum shift
    assert lng == pytest.approx(-81.0, abs=2e-4) and lat == pytest.approx(31 + 50 / 60, abs=2e-4)
    geo = gisio.transformer(NAD27, allow_approximate=True)
    assert geo(-80.0, 32.8) == pytest.approx(_molodensky_nad27(-80.0, 32.8), abs=1e-5)


def test_arcinfo_prj_files():
    sp = gisio.transformer(ARCINFO_SP83_FEET)
    lng, lat = sp(609600.0 / 0.3048006096012192, 0.0)  # ArcInfo FEET are US survey feet
    assert lng == pytest.approx(-81.0, abs=1e-6) and lat == pytest.approx(31 + 50 / 60, abs=1e-6)
    utm27 = gisio.transformer(ARCINFO_UTM27, allow_approximate=True)
    e, n = gisio.tm_forward(-80.0, 32.8, -81.0, a=gisio.CLARKE_1866[0], e2=gisio.CLARKE_1866[1])
    assert utm27(e, n) == pytest.approx(_molodensky_nad27(-80.0, 32.8), abs=1e-5)
    with pytest.raises(ValueError, match="datum"):
        gisio.transformer(ARCINFO_UTM27)
    with pytest.raises(ValueError, match="projection"):
        gisio.transformer("Projection    ALBERS\nDatum NAD83\nUnits METERS\n")


def test_guess_projection_from_coordinates_and_expected_extent():
    quad = [-80.5, 32.25, -80.375, 32.375]  # a 7.5-minute quadrangle
    e0, n0 = gisio.utm_forward(quad[0], quad[1], -81.0)
    e1, n1 = gisio.utm_forward(quad[2], quad[3], -81.0)
    name, to_ll = gisio.guess_transformer([e0, n0, e1, n1], quad)
    assert name.startswith("UTM zone 17N") and to_ll(e0, n0) == pytest.approx((quad[0], quad[1]), abs=1e-6)
    ft = 1 / 0.3048
    sp_x0, sp_y0 = gisio.lcc_forward(quad[0], quad[1], -81.0, 31 + 50 / 60, 32.5, 34 + 50 / 60, 609600.0, 0.0)
    sp_x1, sp_y1 = gisio.lcc_forward(quad[2], quad[3], -81.0, 31 + 50 / 60, 32.5, 34 + 50 / 60, 609600.0, 0.0)
    name, to_ll = gisio.guess_transformer([sp_x0 * ft, sp_y0 * ft, sp_x1 * ft, sp_y1 * ft], quad)
    assert "State Plane" in name and "ft" in name
    assert to_ll(sp_x1 * ft, sp_y1 * ft) == pytest.approx((quad[2], quad[3]), abs=1e-6)
    name, _ = gisio.guess_transformer(quad, quad)
    assert name.startswith("geographic")
    with pytest.raises(ValueError, match="projection"):
        gisio.guess_transformer([1.0, 2.0, 3.0, 4.0], quad)
