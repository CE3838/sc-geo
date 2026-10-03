"""Read GIS data without GDAL: shapefiles (.shp/.dbf/.prj), CSV tables, and
the map projections South Carolina data uses (UTM / Transverse Mercator and
State Plane / Lambert Conformal Conic, any zone, from ESRI WKT or old ArcInfo
.prj files) on NAD83, WGS84 or NAD27.

NAD83 is treated as WGS84 (about 1 m apart). NAD27 is converted only when the
caller allows an approximation (`allow_approximate=True`): coordinates are
unprojected on the Clarke 1866 ellipsoid and moved to NAD83 with the NIMA
three-parameter shift for the conterminous US (dX=-8, dY=160, dZ=176 m;
TR8350.2), good to about 5 m, not the NADCON grids. `datum_note` says when
that happened so callers can flag the source as approximate. Without the
flag, NAD27 raises rather than silently shifting data by tens of meters.
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
GRS80 = (A, E2)
CLARKE_1866 = (6378206.4, (1 / 294.9786982) * (2 - 1 / 294.9786982))
NAD27_SHIFT = (-8.0, 160.0, 176.0)  # meters, NAD27 -> WGS84/NAD83, conterminous US mean (NIMA TR8350.2)
US_FOOT = 1200 / 3937
INTL_FOOT = 0.3048


# --- projections -------------------------------------------------------------

def _meridian_arc(phi: float, a: float = A, e2: float = E2) -> float:
    e4, e6 = e2 * e2, e2 ** 3
    return a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                - (35 * e6 / 3072) * math.sin(6 * phi))


def tm_forward(lng, lat, lon0, k0=0.9996, fe=500000.0, fn=0.0, lat0=0.0, a=A, e2=E2):
    """Transverse Mercator (Snyder 1987, eqs. 8-9 to 8-10), meters."""
    phi, lam = lat * DEG, (lng - lon0) * DEG
    ep2 = e2 / (1 - e2)
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    aa = lam * math.cos(phi)
    m, m0 = _meridian_arc(phi, a, e2), _meridian_arc(lat0 * DEG, a, e2)
    x = k0 * n * (aa + (1 - t + c) * aa ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * aa ** 5 / 120)
    y = k0 * (m - m0 + n * math.tan(phi) * (aa * aa / 2 + (5 - t + 9 * c + 4 * c * c) * aa ** 4 / 24
                                            + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * aa ** 6 / 720))
    return fe + x, fn + y


def tm_inverse(x, y, lon0, k0=0.9996, fe=500000.0, fn=0.0, lat0=0.0, a=A, e2=E2):
    """Inverse Transverse Mercator (Snyder 1987, eqs. 8-12 to 8-25)."""
    ep2 = e2 / (1 - e2)
    m = _meridian_arc(lat0 * DEG, a, e2) + (y - fn) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    c1 = ep2 * math.cos(phi1) ** 2
    t1 = math.tan(phi1) ** 2
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = (x - fe) / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720)
    lng = (d - (1 + 2 * t1 + c1) * d ** 3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120) / math.cos(phi1)
    return lon0 + lng / DEG, lat / DEG


def utm_forward(lng, lat, lon0):
    return tm_forward(lng, lat, lon0)


def _lcc_constants(lat0, lat1, lat2, a, e2):
    e = math.sqrt(e2)
    m = lambda p: math.cos(p) / math.sqrt(1 - e2 * math.sin(p) ** 2)
    t = lambda p: math.tan(math.pi / 4 - p / 2) / ((1 - e * math.sin(p)) / (1 + e * math.sin(p))) ** (e / 2)
    p0, p1, p2 = lat0 * DEG, lat1 * DEG, lat2 * DEG
    n = (math.log(m(p1)) - math.log(m(p2))) / (math.log(t(p1)) - math.log(t(p2))) if p1 != p2 else math.sin(p1)
    big_f = m(p1) / (n * t(p1) ** n)
    return e, t, n, big_f, a * big_f * t(p0) ** n


def lcc_forward(lng, lat, lon0, lat0, lat1, lat2, fe, fn, a=A, e2=E2):
    """Lambert Conformal Conic with two standard parallels (Snyder 1987, eqs. 15-1 to 15-10), meters."""
    _, t, n, big_f, rho0 = _lcc_constants(lat0, lat1, lat2, a, e2)
    rho = a * big_f * t(lat * DEG) ** n
    theta = n * (lng - lon0) * DEG
    return fe + rho * math.sin(theta), fn + rho0 - rho * math.cos(theta)


def lcc_inverse(x, y, lon0, lat0, lat1, lat2, fe, fn, a=A, e2=E2):
    e, _, n, big_f, rho0 = _lcc_constants(lat0, lat1, lat2, a, e2)
    dx, dy = x - fe, rho0 - (y - fn)
    rho = math.copysign(math.hypot(dx, dy), n)
    theta = math.atan2(math.copysign(1, n) * dx, math.copysign(1, n) * dy)
    tt = (rho / (a * big_f)) ** (1 / n)
    phi = math.pi / 2 - 2 * math.atan(tt)
    for _ in range(15):
        es = e * math.sin(phi)
        nxt = math.pi / 2 - 2 * math.atan(tt * ((1 - es) / (1 + es)) ** (e / 2))
        if abs(nxt - phi) < 1e-14:
            phi = nxt
            break
        phi = nxt
    return theta / n / DEG + lon0, phi / DEG


# --- datums ------------------------------------------------------------------

def _to_ecef(lng, lat, a, e2):
    p, l = lat * DEG, lng * DEG
    n = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    return n * math.cos(p) * math.cos(l), n * math.cos(p) * math.sin(l), n * (1 - e2) * math.sin(p)


def _from_ecef(x, y, z, a, e2):
    r = math.hypot(x, y)
    lat = math.atan2(z, r * (1 - e2))
    for _ in range(10):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        h = r / math.cos(lat) - n
        nxt = math.atan2(z, r * (1 - e2 * n / (n + h)))
        if abs(nxt - lat) < 1e-13:
            lat = nxt
            break
        lat = nxt
    return math.atan2(y, x) / DEG, lat / DEG


def nad27_to_nad83(lng: float, lat: float) -> tuple[float, float]:
    """NAD27 -> NAD83 by the conterminous-US three-parameter geocentric shift (about 5 m)."""
    x, y, z = _to_ecef(lng, lat, *CLARKE_1866)
    dx, dy, dz = NAD27_SHIFT
    return _from_ecef(x + dx, y + dy, z + dz, *GRS80)


def _datum_kind(name: str) -> str | None:
    if re.search(r"North_American_1983|NAD_?1983|NAD_?83|WGS_?1984|WGS_?84", name, re.I):
        return "nad83"
    if re.search(r"North_American_1927|NAD_?1927|NAD_?27", name, re.I):
        return "nad27"
    return None


def _is_arcinfo(prj: str) -> bool:
    return bool(re.match(r"\s*Projection\s", prj, re.I))


def _arcinfo_fields(prj: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2).strip() for m in re.finditer(r"^[ \t]*(\w+)[ \t]+(\S.*?)[ \t]*$", prj, re.M)}


def _datum_of(prj: str) -> str:
    if _is_arcinfo(prj):
        return _arcinfo_fields(prj).get("datum", "")
    return (re.search(r'DATUM\["([^"]+)"', prj) or [None, ""])[1]


def datum_note(prj: str) -> str | None:
    """A note for sources whose positions are approximate because of their datum, else None."""
    if _datum_kind(_datum_of(prj)) == "nad27":
        return "NAD27 converted to NAD83 with the conterminous-US 3-parameter shift (about 5 m)"
    return None


# State Plane zones that ArcInfo .prj files name by FIPS code:
# Lambert Conformal Conic (lon0, lat0, lat1, lat2, false easting in meters).
_FIPS = {
    ("3900", "nad83"): (-81.0, 31 + 50 / 60, 32.5, 34 + 50 / 60, 609600.0),
    ("3901", "nad27"): (-81.0, 33.0, 33 + 46 / 60, 34 + 58 / 60, 2_000_000 * US_FOOT),
    ("3902", "nad27"): (-81.0, 31 + 50 / 60, 32 + 20 / 60, 33 + 40 / 60, 2_000_000 * US_FOOT),
}


def _with_datum(to_ll, kind: str | None, allow_approximate: bool):
    if kind == "nad83":
        return to_ll
    if kind == "nad27" and allow_approximate:
        return lambda x, y: nad27_to_nad83(*to_ll(x, y))
    raise ValueError(f"Unsupported datum: {kind or 'unknown'}"
                     + (" (pass allow_approximate=True to shift NAD27)" if kind == "nad27" else ""))


def _arcinfo_transformer(prj: str, allow_approximate: bool):
    f = _arcinfo_fields(prj)
    spheroid = f.get("spheroid", "").lower()
    kind = _datum_kind(f.get("datum", "")) or ("nad27" if "clarke" in spheroid else
                                               "nad83" if "grs" in spheroid else None)
    if kind is None:
        raise ValueError(f"Unsupported datum: {f.get('datum') or 'unknown'}")
    a, e2 = CLARKE_1866 if kind == "nad27" else GRS80
    units = f.get("units", "METERS").upper()
    # ArcInfo FEET are US survey feet.
    to_m = {"METERS": 1.0, "FEET": US_FOOT, "INTERNATIONAL_FEET": INTL_FOOT}.get(units)
    proj = f.get("projection", "").upper()
    if proj == "GEOGRAPHIC":
        to_ll = lambda x, y: (x, y)
    elif proj == "UTM" and to_m and f.get("zone", "").isdigit():
        lon0 = -183.0 + 6 * int(f["zone"])
        to_ll = lambda x, y: tm_inverse(x * to_m, y * to_m, lon0, a=a, e2=e2)
    elif proj == "STATEPLANE" and to_m and (f.get("fipszone"), kind) in _FIPS:
        lon0, lat0, lat1, lat2, fe = _FIPS[(f.get("fipszone"), kind)]
        to_ll = lambda x, y: lcc_inverse(x * to_m, y * to_m, lon0, lat0, lat1, lat2, fe, 0.0, a=a, e2=e2)
    else:
        raise ValueError(f"Unsupported projection: {proj} {f.get('fipszone') or f.get('zone') or ''} {units}")
    return _with_datum(to_ll, kind, allow_approximate)


def transformer(wkt: str, allow_approximate: bool = False) -> Callable[[float, float], tuple[float, float]]:
    """(x, y) -> (lon, lat) on NAD83 for a .prj file (ESRI WKT or old ArcInfo format)."""
    if _is_arcinfo(wkt):
        return _arcinfo_transformer(wkt, allow_approximate)
    kind = _datum_kind(_datum_of(wkt))
    if kind is None:
        raise ValueError(f"Unsupported datum: {_datum_of(wkt) or 'unknown'}")
    sph = re.search(r'SPHEROID\["[^"]*",\s*([-\d.eE+]+),\s*([-\d.eE+]+)', wkt)
    if sph:
        a, invf = float(sph.group(1)), float(sph.group(2))
        e2 = 0.0 if invf == 0 else (1 / invf) * (2 - 1 / invf)
    else:
        a, e2 = CLARKE_1866 if kind == "nad27" else GRS80
    if not wkt.lstrip().upper().startswith("PROJCS"):
        return _with_datum(lambda x, y: (x, y), kind, allow_approximate)
    proj = re.search(r'PROJECTION\["([^"]+)"', wkt).group(1).lower()
    params = {k.lower(): float(v) for k, v in re.findall(r'PARAMETER\["([^"]+)",\s*([-\d.eE+]+)\]', wkt)}
    units = re.findall(r'UNIT\["([^"]+)",\s*([-\d.eE+]+)', wkt)
    to_m = float(units[-1][1]) if units else 1.0
    fe, fn = params.get("false_easting", 0) * to_m, params.get("false_northing", 0) * to_m
    lon0 = params.get("central_meridian", params.get("longitude_of_center", 0))
    lat0 = params.get("latitude_of_origin", params.get("latitude_of_center", 0))
    if "transverse_mercator" in proj:
        k0 = params.get("scale_factor", 1.0)
        to_ll = lambda x, y: tm_inverse(x * to_m, y * to_m, lon0, k0, fe, fn, lat0, a=a, e2=e2)
    elif "lambert_conformal_conic" in proj:
        lat1 = params.get("standard_parallel_1", lat0)
        lat2 = params.get("standard_parallel_2", lat1)
        to_ll = lambda x, y: lcc_inverse(x * to_m, y * to_m, lon0, lat0, lat1, lat2, fe, fn, a=a, e2=e2)
    else:
        raise ValueError(f"Unsupported projection: {proj}")
    return _with_datum(to_ll, kind, allow_approximate)


# Coordinate systems South Carolina data comes in, most likely first, for files without a .prj.
GUESSES = [
    ("geographic (NAD83 assumed)", "Projection GEOGRAPHIC\nDatum NAD83\nUnits DD\n"),
    ("UTM zone 17N meters (NAD83 assumed)", "Projection UTM\nZone 17\nDatum NAD83\nUnits METERS\n"),
    ("SC State Plane NAD83 ft (international)",
     "Projection STATEPLANE\nFipszone 3900\nDatum NAD83\nUnits INTERNATIONAL_FEET\n"),
    ("SC State Plane NAD83 meters", "Projection STATEPLANE\nFipszone 3900\nDatum NAD83\nUnits METERS\n"),
    ("SC State Plane NAD27 South ft (US survey)", "Projection STATEPLANE\nFipszone 3902\nDatum NAD27\nUnits FEET\n"),
    ("SC State Plane NAD27 North ft (US survey)", "Projection STATEPLANE\nFipszone 3901\nDatum NAD27\nUnits FEET\n"),
]


def guess_transformer(xy_bbox, expected_lonlat_bbox, margin: float = 0.05):
    """(name, transformer) for data without a .prj: the candidate system that puts the data's
    extent inside the expected extent (such as the catalog's quadrangle bounds), closest to it.

    Raises ValueError when no candidate fits. A guess is approximate: callers flag it."""
    x0, y0, x1, y1 = xy_bbox
    w, s, e, n = expected_lonlat_bbox
    best = None
    for i, (name, prj) in enumerate(GUESSES):
        to_ll = transformer(prj, allow_approximate=True)
        try:
            pts = [to_ll(x, y) for x in (x0, x1) for y in (y0, y1)]
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
        lons, lats = [p[0] for p in pts], [p[1] for p in pts]
        if not all(math.isfinite(v) for v in lons + lats):
            continue
        if min(lons) < w - margin or max(lons) > e + margin or min(lats) < s - margin or max(lats) > n + margin:
            continue
        dist = max(abs(min(lons) - w), abs(max(lons) - e), abs(min(lats) - s), abs(max(lats) - n))
        key = (round(dist, 3), i)
        if best is None or key < best[0]:
            best = (key, name, to_ll)
    if best is None:
        raise ValueError(f"Unknown projection: no .prj, and no known system puts {list(xy_bbox)} "
                         f"inside {list(expected_lonlat_bbox)}")
    return best[1], best[2]


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


def map_coords(c, f):
    """Apply f(x, y) -> (lon, lat) to nested GeoJSON coordinates."""
    return list(f(c[0], c[1])) if isinstance(c[0], (int, float)) else [map_coords(x, f) for x in c]



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
            feat["geometry"]["coordinates"] = map_coords(feat["geometry"]["coordinates"], to_ll)
            yield feat


def zip_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    hits = [n for n in zf.namelist() if n.lower().endswith(f"/{name.lower()}.csv")]
    hits.sort(key=lambda p: ("gems_shapefiles" not in p.lower(), len(p)))
    if not hits:
        return []
    text = zf.read(hits[0]).decode("utf-8-sig", "replace")
    return list(csv.DictReader(io.StringIO(text)))
