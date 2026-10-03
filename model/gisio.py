"""Read GIS data without GDAL: shapefiles (.shp/.dbf/.prj), CSV tables, and
the map projections South Carolina data uses (UTM / Transverse Mercator and
State Plane / Lambert Conformal Conic) on NAD83 or WGS84.

NAD83 is treated as WGS84 (about 1 m apart). Other datums (NAD27) raise
rather than silently shift data by tens of meters.
"""

from __future__ import annotations

import csv
import io
import math
import re
import struct
import zipfile
from typing import Callable, Iterator

A = 6378137.0
F = 1 / 298.257222101
E2 = F * (2 - F)
DEG = math.pi / 180


# --- projections -------------------------------------------------------------

def _meridian_arc(phi: float) -> float:
    e2, e4, e6 = E2, E2 * E2, E2 ** 3
    return A * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                - (35 * e6 / 3072) * math.sin(6 * phi))


def tm_forward(lng, lat, lon0, k0=0.9996, fe=500000.0, fn=0.0, lat0=0.0):
    """Transverse Mercator (Snyder 1987, eqs. 8-9 to 8-10), meters."""
    phi, lam = lat * DEG, (lng - lon0) * DEG
    ep2 = E2 / (1 - E2)
    n = A / math.sqrt(1 - E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    a = lam * math.cos(phi)
    m, m0 = _meridian_arc(phi), _meridian_arc(lat0 * DEG)
    x = k0 * n * (a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * a ** 5 / 120)
    y = k0 * (m - m0 + n * math.tan(phi) * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24
                                            + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * a ** 6 / 720))
    return fe + x, fn + y


def tm_inverse(x, y, lon0, k0=0.9996, fe=500000.0, fn=0.0, lat0=0.0):
    """Inverse Transverse Mercator (Snyder 1987, eqs. 8-12 to 8-25)."""
    ep2 = E2 / (1 - E2)
    m = _meridian_arc(lat0 * DEG) + (y - fn) / k0
    mu = m / (A * (1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    c1 = ep2 * math.cos(phi1) ** 2
    t1 = math.tan(phi1) ** 2
    n1 = A / math.sqrt(1 - E2 * math.sin(phi1) ** 2)
    r1 = A * (1 - E2) / (1 - E2 * math.sin(phi1) ** 2) ** 1.5
    d = (x - fe) / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720)
    lng = (d - (1 + 2 * t1 + c1) * d ** 3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120) / math.cos(phi1)
    return lon0 + lng / DEG, lat / DEG


def utm_forward(lng, lat, lon0):
    return tm_forward(lng, lat, lon0)


def lcc_inverse(x, y, lon0, lat0, lat1, lat2, fe, fn):
    e = math.sqrt(E2)
    m = lambda p: math.cos(p) / math.sqrt(1 - E2 * math.sin(p) ** 2)
    t = lambda p: math.tan(math.pi / 4 - p / 2) / ((1 - e * math.sin(p)) / (1 + e * math.sin(p))) ** (e / 2)
    p0, p1, p2 = lat0 * DEG, lat1 * DEG, lat2 * DEG
    n = (math.log(m(p1)) - math.log(m(p2))) / (math.log(t(p1)) - math.log(t(p2))) if p1 != p2 else math.sin(p1)
    big_f = m(p1) / (n * t(p1) ** n)
    rho0 = A * big_f * t(p0) ** n
    dx, dy = x - fe, rho0 - (y - fn)
    rho = math.copysign(math.hypot(dx, dy), n)
    theta = math.atan2(math.copysign(1, n) * dx, math.copysign(1, n) * dy)
    tt = (rho / (A * big_f)) ** (1 / n)
    phi = math.pi / 2 - 2 * math.atan(tt)
    for _ in range(15):
        es = e * math.sin(phi)
        nxt = math.pi / 2 - 2 * math.atan(tt * ((1 - es) / (1 + es)) ** (e / 2))
        if abs(nxt - phi) < 1e-14:
            phi = nxt
            break
        phi = nxt
    return theta / n / DEG + lon0, phi / DEG


def transformer(wkt: str) -> Callable[[float, float], tuple[float, float]]:
    """(x, y) -> (lon, lat) for a .prj WKT string."""
    datum = (re.search(r'DATUM\["([^"]+)"', wkt) or [None, ""])[1]
    if not re.search(r"North_American_1983|NAD_?1983|NAD83|WGS_?1984|WGS84", datum, re.I):
        raise ValueError(f"Unsupported datum: {datum or 'unknown'}")
    if not wkt.lstrip().upper().startswith("PROJCS"):
        return lambda x, y: (x, y)
    proj = re.search(r'PROJECTION\["([^"]+)"', wkt).group(1).lower()
    params = {k.lower(): float(v) for k, v in re.findall(r'PARAMETER\["([^"]+)",\s*([-\d.eE+]+)\]', wkt)}
    units = re.findall(r'UNIT\["([^"]+)",\s*([-\d.eE+]+)', wkt)
    to_m = float(units[-1][1]) if units else 1.0
    fe, fn = params.get("false_easting", 0) * to_m, params.get("false_northing", 0) * to_m
    lon0 = params.get("central_meridian", params.get("longitude_of_center", 0))
    lat0 = params.get("latitude_of_origin", params.get("latitude_of_center", 0))
    if "transverse_mercator" in proj:
        k0 = params.get("scale_factor", 1.0)
        return lambda x, y: tm_inverse(x * to_m, y * to_m, lon0, k0, fe, fn, lat0)
    if "lambert_conformal_conic" in proj:
        lat1 = params.get("standard_parallel_1", lat0)
        lat2 = params.get("standard_parallel_2", lat1)
        return lambda x, y: lcc_inverse(x * to_m, y * to_m, lon0, lat0, lat1, lat2, fe, fn)
    raise ValueError(f"Unsupported projection: {proj}")


# --- shapefiles --------------------------------------------------------------

def _signed_area(ring) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))


def _inside(pt, ring) -> bool:
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _polygon(rings: list[list[list[float]]]) -> dict | None:
    outers, holes = [], []
    for r in rings:
        (outers if _signed_area(r) <= 0 else holes).append(r)   # shapefile outer rings are clockwise
    if not outers:
        outers, holes = holes, []
    polys = [[o] for o in outers]
    for h in holes:
        host = next((p for p in polys if _inside(h[0], p[0])), polys[0])
        host.append(h)
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}


def _read_dbf(f) -> Iterator[dict]:
    head = f.read(32)
    n, header_len, rec_len = struct.unpack("<IHH", head[4:12])
    fields = []
    while True:
        d = f.read(32)
        if not d or d[0] == 0x0D:
            break
        name = d[:11].split(b"\x00")[0].decode("latin-1").strip()
        fields.append((name, chr(d[11]), d[16]))
    f.seek(header_len)
    for _ in range(n):
        rec = f.read(rec_len)
        if not rec or rec[:1] == b"*":
            continue
        out, pos = {}, 1
        for name, kind, width in fields:
            raw = rec[pos:pos + width]
            pos += width
            try:
                text = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                text = raw.decode("latin-1").strip()
            if kind in "NF" and text:
                try:
                    out[name] = float(text) if "." in text else int(text)
                except ValueError:
                    out[name] = text
            else:
                out[name] = text
        yield out


def read_shapefile(shp, dbf) -> Iterator[dict]:
    """Features (GeoJSON-like, source coordinates) from polygon or line shapefiles."""
    data = shp.read()
    attrs = list(_read_dbf(dbf)) if dbf is not None else []
    pos, i = 100, 0
    while pos + 8 <= len(data):
        _, length = struct.unpack(">2i", data[pos:pos + 8])
        content = data[pos + 8:pos + 8 + length * 2]
        pos += 8 + length * 2
        props = attrs[i] if i < len(attrs) else {}
        i += 1
        stype = struct.unpack("<i", content[:4])[0]
        if stype == 0:
            continue
        if stype not in (3, 5, 13, 15, 23, 25):
            raise ValueError(f"Unsupported shape type {stype}")
        nparts, npts = struct.unpack("<2i", content[36:44])
        parts = list(struct.unpack(f"<{nparts}i", content[44:44 + 4 * nparts]))
        off = 44 + 4 * nparts
        pts = [list(struct.unpack("<2d", content[off + 16 * k: off + 16 * k + 16])) for k in range(npts)]
        rings = [pts[a:b] for a, b in zip(parts, parts[1:] + [npts])]
        if stype in (5, 15, 25):
            geom = _polygon(rings)
        else:
            geom = {"type": "LineString", "coordinates": rings[0]} if len(rings) == 1 else \
                {"type": "MultiLineString", "coordinates": rings}
        yield {"type": "Feature", "geometry": geom, "properties": props}


def _map_coords(c, f):
    return list(f(c[0], c[1])) if isinstance(c[0], (int, float)) else [_map_coords(x, f) for x in c]


def zip_layer(zf: zipfile.ZipFile, name: str) -> str | None:
    """Path (without extension) of a shapefile layer in a zip, preferring GeMS_shapefiles/."""
    hits = [n[:-4] for n in zf.namelist() if n.lower().endswith(f"/{name.lower()}.shp") or n.lower() == f"{name.lower()}.shp"]
    hits.sort(key=lambda p: ("gems_shapefiles" not in p.lower(), len(p)))
    return hits[0] if hits else None


def read_layer_lonlat(zf: zipfile.ZipFile, base: str) -> Iterator[dict]:
    names = {n.lower(): n for n in zf.namelist()}
    prj = names.get(f"{base}.prj".lower())
    to_ll = transformer(zf.read(prj).decode("latin-1")) if prj else (lambda x, y: (x, y))
    dbf_name = names.get(f"{base}.dbf".lower())
    with zf.open(names[f"{base}.shp".lower()]) as shp:
        dbf = io.BytesIO(zf.read(dbf_name)) if dbf_name else None
        for feat in read_shapefile(io.BytesIO(shp.read()), dbf):
            feat["geometry"]["coordinates"] = _map_coords(feat["geometry"]["coordinates"], to_ll)
            yield feat


def zip_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    hits = [n for n in zf.namelist() if n.lower().endswith(f"/{name.lower()}.csv")]
    hits.sort(key=lambda p: ("gems_shapefiles" not in p.lower(), len(p)))
    if not hits:
        return []
    text = zf.read(hits[0]).decode("utf-8-sig", "replace")
    return list(csv.DictReader(io.StringIO(text)))
