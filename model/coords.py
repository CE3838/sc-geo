"""Printed locations to latitude/longitude (NAD83), without silent guesses.

`parse(text)` reads one coordinate pair as a document prints it:

* decimal degrees ("32.7765, -79.9311", "32.7765 N, 79.9311 W");
* degrees-minutes-seconds in the usual printed forms (32°46'35" N, 32 46 35 N,
  32-46-35N, 32:46:35, "32 deg 46 min 35 sec", decimal minutes);
* USGS packed DDMMSS / DDDMMSS ("lat 332041, long 0815210");
* South Carolina State Plane: NAD83 (FIPS 3900) in international feet, US
  survey feet or metres, and NAD27 North/South zones (US survey feet),
  through the projections in model/gisio.py. NAD27 is shifted to NAD83 with
  gisio's three-parameter shift (about 5 m) and marked approximate.

It returns None whenever the text is ambiguous: no pair or more than one,
two latitudes, minutes or seconds of 60 or more, State Plane without a datum
(NAD27 and NAD83 grid values differ by hundreds of feet), NAD27 without its
zone, mixed units, or a point outside South Carolina and its neighbours.
Anything it had to assume (western longitude, unstated horizontal datum,
feet from the easting's size) is listed in `assumptions`. A converted
coordinate is never a reading: callers store it flagged inferred.
"""

from __future__ import annotations

import re

from model import gisio

# South Carolina with a margin (Savannah River sites in Georgia, the NC line).
REGION = {"lat": (31.5, 35.6), "lon": (-84.0, -78.0)}
CONVERSION = "model.coords"

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_LAT_LABEL = re.compile(r"(?i)\blat(?:itude)?\.?\s*[:=]?\s*$")
_LON_LABEL = re.compile(r"(?i)\b(?:lon|long|longitude)\.?\s*[:=]?\s*$")

_SYM = re.compile(
    r"(?P<d>\d{1,3}(?:\.\d+)?)\s*(?:°|º|˚|(?i:deg(?:rees|s)?\.?))\s*"
    r"(?:(?P<m>\d{1,2}(?:\.\d+)?)\s*(?:'|′|’|(?i:min(?:utes|s)?\.?))\s*)?"
    r"(?:(?P<s>\d{1,2}(?:\.\d+)?)\s*(?:\"|″|”|''|′′|(?i:sec(?:onds|s)?\.?)))?")
_SEP = re.compile(r"(?<![\d.])(?P<d>\d{1,3})(?P<sep>[ :-])(?P<m>\d{1,2})"
                  r"(?P=sep)(?P<s>\d{1,2}(?:\.\d+)?)(?![\d])")
_PACKED = re.compile(r"(?<![\d.,])(?P<n>\d{6,7})(?P<f>\.\d+)?(?!\d|,\d)")
_DEC = re.compile(r"(?<![\d.])(?P<sign>[-−])?(?P<d>\d{1,3}\.\d+)"
                  r"(?!\d|\s*(?:ft|feet|foot|m\b|meters?|metres?|mi\b|miles?|km|%|in\b))")


def _datum(s: str) -> str | None | bool:
    """'NAD83', 'NAD27', None (not stated) or False (more than one)."""
    found = set()
    if re.search(r"(?i)\bNAD\s*-?\s*(?:19)?83\b|\bHARN\b|\bWGS\s*-?\s*(?:19)?84\b|North American Datum of 1983", s):
        found.add("NAD83")
    if re.search(r"(?i)\bNAD\s*-?\s*(?:19)?27\b|North American Datum of 1927", s):
        found.add("NAD27")
    if len(found) > 1:
        return False
    return found.pop() if found else None


def _result(lat, lon, fmt, datum, assumptions, conversion):
    if datum == "NAD27":
        lon, lat = gisio.nad27_to_nad83(lon, lat)
    if not (REGION["lat"][0] <= lat <= REGION["lat"][1] and REGION["lon"][0] <= lon <= REGION["lon"][1]):
        return None
    if datum is None:
        assumptions = assumptions + ["horizontal datum not stated"]
    return {"lat": lat, "lon": lon, "format": fmt, "datum": datum, "approximate": datum is None or datum == "NAD27",
            "assumptions": assumptions, "conversion": f"{CONVERSION}: {conversion}"
            + (" (NAD27 shifted to NAD83, about 5 m)" if datum == "NAD27" else "")}


# --- State Plane --------------------------------------------------------------

_UNITS_M = {"ft": gisio.INTL_FOOT, "us_ft": gisio.US_FOOT, "m": 1.0}
_FIPS83 = ("3900", "nad83")


def _zone(datum: str, zone: str | None) -> tuple:
    if datum == "NAD83":
        return gisio._FIPS[_FIPS83], gisio.GRS80
    key = {"north": "3901", "south": "3902"}.get((zone or "").lower(), zone)
    if (key, "nad27") not in gisio._FIPS:
        raise ValueError(f"NAD27 State Plane needs its zone (north or south), got {zone!r}")
    return gisio._FIPS[(key, "nad27")], gisio.CLARKE_1866


def state_plane_to_latlon(easting: float, northing: float, datum: str = "NAD83", unit: str = "ft",
                          zone: str | None = None) -> tuple[float, float]:
    """(lat, lon) on the datum's own ellipsoid (no datum shift) from SC State Plane.

    unit: 'ft' (international foot), 'us_ft' or 'm'. NAD27 zones: 'north' or 'south'."""
    (lon0, lat0, lat1, lat2, fe), (a, e2) = _zone(datum, zone)
    k = _UNITS_M[unit]
    lon, lat = gisio.lcc_inverse(easting * k, northing * k, lon0, lat0, lat1, lat2, fe, 0.0, a=a, e2=e2)
    return lat, lon


def latlon_to_state_plane(lat: float, lon: float, datum: str = "NAD83", unit: str = "ft",
                          zone: str | None = None) -> tuple[float, float]:
    """(easting, northing) in `unit` from lat/lon on the datum's own ellipsoid."""
    (lon0, lat0, lat1, lat2, fe), (a, e2) = _zone(datum, zone)
    x, y = gisio.lcc_forward(lon, lat, lon0, lat0, lat1, lat2, fe, 0.0, a=a, e2=e2)
    k = _UNITS_M[unit]
    return x / k, y / k


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def _labelled(s: str, labels: str) -> list[float]:
    pre = {_f(m.group(1)) for m in re.finditer(rf"(?i)(?:{labels})\s*[:=]?\s*({_NUM})", s)}
    if pre:
        return sorted(pre)
    post = re.finditer(rf"(?i)(?<![\d.,])({_NUM})\s*(?:ft|feet|m|meters?|metres?)?\.?\s*(?:{labels})(?![A-Za-z])", s)
    return sorted({_f(m.group(1)) for m in post})


def _state_plane(s: str) -> dict | None:
    eastings = _labelled(s, r"\beasting\b|\bE\b|\bX\b")
    northings = _labelled(s, r"\bnorthing\b|\bN\b|\bY\b")
    if len(eastings) != 1 or len(northings) != 1:
        return None
    e, n = eastings[0], northings[0]
    datum = _datum(s)
    if not datum:
        return None
    zone = None
    if datum == "NAD27":
        m = re.search(r"(?i)\b(north|south)(?:ern)?\s+zone\b|\bzone\s*[:=]?\s*(north|south|390[12])\b|\b(390[12])\b", s)
        if not m:
            return None
        zone = next(g for g in m.groups() if g).lower()
    survey = bool(re.search(r"(?i)\b(?:u\.?s\.?\s*)?survey\s*f(?:ee|oo)t|\busft\b|\bus\s*ft\b", s))
    metres = bool(re.search(r"(?i)\d\s*(?:m|meters?|metres?)\b|\((?:m|meters?|metres?)\)", s))
    feet = bool(re.search(r"(?i)\b(?:ft|feet|foot)\b", s)) or survey
    assumptions = []
    if metres and feet:
        return None
    if datum == "NAD27":
        if metres:
            return None
        unit = "us_ft"  # NAD27 State Plane was defined in US survey feet
        if not feet:
            assumptions.append("US survey feet assumed (NAD27 State Plane)")
    elif survey:
        unit = "us_ft"
    elif metres:
        unit = "m"
    elif feet:
        unit = "ft"
    elif 1_200_000 <= e <= 2_900_000:
        unit = "ft"
        assumptions.append("international feet assumed from the size of the easting")
    elif 360_000 <= e <= 890_000:
        unit = "m"
        assumptions.append("metres assumed from the size of the easting")
    else:
        return None
    lat, lon = state_plane_to_latlon(e, n, datum, unit, zone)
    label = {"ft": "international feet", "us_ft": "US survey feet", "m": "metres"}[unit]
    fips = "FIPS 3900" if datum == "NAD83" else f"{zone} zone"
    return _result(lat, lon, "state_plane", datum, assumptions,
                   f"SC State Plane {datum} ({fips}), {label}, to latitude/longitude")


# --- geographic -----------------------------------------------------------------

def _prefix(s: str, m: re.Match) -> str | None:
    p = re.search(r"(?<![A-Za-z])([NSEW])\.?\s*$", s[:m.start()])
    return p.group(1) if p else None


def _suffix(s: str, m: re.Match) -> str | None:
    p = re.match(r"\s*([NSEW])(?![A-Za-z])", s[m.end():])
    return p.group(1) if p else None


def _angles(s: str, matches: list[re.Match]) -> list[tuple[re.Match, str | None, str | None]]:
    """(match, hint 'lat'/'lon'/'conflict'/None, hemisphere letter) for each angle.

    Hemisphere letters are prefixes ("N32 46 35") when the first angle has one, else suffixes."""
    prefix = bool(matches) and _prefix(s, matches[0]) is not None
    out = []
    for m in matches:
        h = _prefix(s, m) if prefix else _suffix(s, m)
        kinds = set()
        if h:
            kinds.add("lat" if h in "NS" else "lon")
        before = s[max(0, m.start() - 14):m.start()]
        if _LAT_LABEL.search(before):
            kinds.add("lat")
        elif _LON_LABEL.search(before):
            kinds.add("lon")
        out.append((m, "conflict" if len(kinds) > 1 else (kinds.pop() if kinds else None), h))
    return out


def _pair(s: str, angles: list[tuple[float, str | None, str | None, bool]], fmt: str, what: str,
          need_hints: bool = False) -> dict | None:
    """angles: (degrees, hint, hemisphere letter, negative sign printed)."""
    if len(angles) != 2:
        return None
    hints = [a[1] for a in angles]
    if "conflict" in hints or (hints[0] and hints[0] == hints[1]):
        return None
    if need_hints and not any(hints):
        return None
    if hints[0] == "lon" or hints[1] == "lat":
        angles = angles[::-1]
    elif not any(hints):
        mags = [abs(a[0]) for a in angles]
        if 24 <= mags[0] <= 50 and 66 <= mags[1] <= 125:
            pass
        elif 24 <= mags[1] <= 50 and 66 <= mags[0] <= 125:
            angles = angles[::-1]
        else:
            return None
    (lat, _, lat_h, lat_neg), (lon, _, lon_h, lon_neg) = angles
    if lat_neg or lat_h == "S" or lon_h == "E":
        return None  # southern or eastern hemisphere: not South Carolina
    assumptions = []
    if not (lon_neg or lon_h == "W"):
        assumptions.append("western longitude assumed (no sign or W printed)")
    datum = _datum(s)
    if datum is False:
        return None
    return _result(lat, -abs(lon), fmt, datum, assumptions, f"{what} to decimal degrees")


def _dms(d: float, m: str | None, sec: str | None) -> float | None:
    mm = float(m) if m else 0.0
    ss = float(sec) if sec else 0.0
    if mm >= 60 or ss >= 60 or (m is None and sec is not None):
        return None
    return d + mm / 60 + ss / 3600


def parse(text) -> dict | None:
    """{'lat', 'lon', 'format', 'datum', 'approximate', 'assumptions', 'conversion'} or None."""
    if not isinstance(text, str):
        return None
    s = re.sub(r"\s+", " ", text)[:500]
    if not re.search(r"\d", s):
        return None
    cue = re.search(r"(?i)easting|northing|state\s*plane|\bspcs\b|\bfips\b|\b[XY]\s*[:=]"
                    r"|\b[EN]\s*[:=]?\s*(?:\d{1,3}(?:,\d{3})+|\d{5,})", s)
    big = [x for x in re.findall(_NUM, s) if _f(x) >= 10_000 and not re.fullmatch(r"\d{6,7}(?:\.\d+)?", x)]
    if cue or big:
        return _state_plane(s)
    sym = list(_SYM.finditer(s))
    if sym:
        angles = []
        decimal = all(m.group("m") is None for m in sym)
        for m, hint, hemi in _angles(s, sym):
            if "." in m.group("d") and m.group("m"):
                return None
            deg = _dms(float(m.group("d")), m.group("m"), m.group("s"))
            if deg is None:
                return None
            angles.append((deg, hint, hemi, s[max(0, m.start() - 1):m.start()] in ("-", "−")))
        if decimal:
            return _pair(s, angles, "decimal", "decimal degrees")
        return _pair(s, angles, "dms", "degrees, minutes and seconds")
    sep = list(_SEP.finditer(s))
    if sep:
        angles = []
        for m, hint, hemi in _angles(s, sep):
            deg = _dms(float(m.group("d")), m.group("m"), m.group("s"))
            if deg is None:
                return None
            angles.append((deg, hint, hemi, False))
        if all(a[1] for a in angles):
            return _pair(s, angles, "dms", "degrees, minutes and seconds")
        return None
    packed = list(_PACKED.finditer(s))
    if packed:
        angles = []
        for m, hint, hemi in _angles(s, packed):
            n = m.group("n")
            d, mm, ss = (n[:3], n[3:5], n[5:]) if len(n) == 7 else (n[:2], n[2:4], n[4:])
            deg = _dms(float(d), mm, ss + (m.group("f") or ""))
            if deg is None:
                return None
            angles.append((deg, hint, hemi, False))
        seven = len(packed) == 2 and len(packed[0].group("n")) == 6 and len(packed[1].group("n")) == 7 \
            and packed[1].group("n").startswith("0")
        return _pair(s, angles, "packed_dms", "packed DDMMSS/DDDMMSS (USGS)", need_hints=not seven)
    dec = list(_DEC.finditer(s))
    if dec:
        angles = [(float(m.group("d")), hint, hemi, bool(m.group("sign"))) for m, hint, hemi in _angles(s, dec)]
        return _pair(s, angles, "decimal", "decimal degrees")
    return None
