"""Deterministic normalizers applied AFTER the reading model has picked a value.

These never decide what a document says; they only convert a value the model
quoted into a standard form (feet, Munsell parts, USCS symbols, SPT N, strike
azimuth, WGS84-ish decimal degrees, Ma ranges, Geolex names). Each returns
None when the text does not parse, so the original text is kept as stated.
Results that rest on an assumption carry a flag saying so (`inferred`,
`hemisphere_inferred`, `convention_inferred`, `datum_inferred`).
"""

from __future__ import annotations

import math
import re

from model.units import AGE_SOURCE, Lexicon, age_range, name_key

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+"


def _f(s: str) -> float:
    return float(s.replace(",", ""))


# --- Munsell -----------------------------------------------------------------

_MUNSELL = re.compile(r"(?<![A-Za-z0-9.])(?:(\d{1,2}(?:\.\d)?)\s*(YR|GY|BG|PB|RP|Y|R|G|B|P)|(N))\s*"
                      r"(\d{1,2}(?:\.\d+)?)\s*/\s*(\d{1,2}(?:\.\d+)?)?", re.I)


def munsell(text) -> dict | None:
    m = _MUNSELL.search(str(text or ""))
    if not m:
        return None
    hue = "N" if m.group(3) else f"{m.group(1)}{m.group(2).upper()}"
    value = _f(m.group(4))
    chroma = _f(m.group(5)) if m.group(5) else 0
    value = int(value) if value == int(value) else value
    chroma = int(chroma) if chroma == int(chroma) else chroma
    if not 0 <= value <= 10:
        return None
    notation = f"{hue} {value}/" + ("" if hue == "N" else f"{chroma}")
    return {"hue": hue, "value": value, "chroma": chroma, "notation": notation}


# --- lengths -----------------------------------------------------------------

_UNITS = {"ft": 1.0, "feet": 1.0, "foot": 1.0, "'": 1.0, "m": 1 / 0.3048, "meter": 1 / 0.3048,
          "meters": 1 / 0.3048, "metre": 1 / 0.3048, "metres": 1 / 0.3048, "in": 1 / 12, "in.": 1 / 12,
          "inch": 1 / 12, "inches": 1 / 12, '"': 1 / 12, "cm": 1 / 30.48, "mm": 1 / 304.8, "km": 1000 / 0.3048}
_UNIT_RE = r"(feet|foot|ft\.?|meters?|metres?|m\b|inch(?:es)?|in\.?|cm|mm|km|'|\")"
_RANGE = re.compile(rf"({_NUM})\s*{_UNIT_RE}?\s*(?:-|–|—|to)\s*({_NUM})\s*{_UNIT_RE}", re.I)
_SINGLE = re.compile(rf"({_NUM})\s*{_UNIT_RE}", re.I)
_FT_IN = re.compile(rf"({_NUM})\s*'\s*({_NUM})\s*\"")
_UPPER = re.compile(r"as much as|up to|less than|<|maximum|max\.|no more than", re.I)
_LOWER = re.compile(r"more than|greater than|>|at least|minimum|exceeds|over\b", re.I)


def _unit_factor(u: str) -> float:
    return _UNITS[u.lower().rstrip(".") if u.lower() not in ("in.",) else "in"]


def length_ft(text, default_unit: str | None = None) -> dict | None:
    """{'min_ft', 'max_ft', 'unit', 'approximate'} from '10 to 15 ft', '3.5 m', "5' 6\"", ..."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        if not default_unit:
            return None
        v = float(text) * _unit_factor(default_unit)
        return {"min_ft": v, "max_ft": v, "unit": default_unit, "approximate": False}
    s = re.sub(r"\s+", " ", str(text or ""))[:1000]  # a single value; bounded so no regex can stall
    approx = bool(re.search(r"\b(about|approximately|approx\.?|roughly|ca\.)\b|~", s, re.I))
    m = _FT_IN.search(s)
    if m:
        v = _f(m.group(1)) + _f(m.group(2)) / 12
        return {"min_ft": v, "max_ft": v, "unit": "ft", "approximate": approx}
    lo = hi = None
    unit = None
    m = _RANGE.search(s)
    if m:
        unit = m.group(4)
        lo_unit = m.group(2) or unit
        lo, hi = _f(m.group(1)) * _unit_factor(lo_unit), _f(m.group(3)) * _unit_factor(unit)
    else:
        found = list(_SINGLE.finditer(s))
        if len(found) > 1:
            # Several separate lengths ('24 ft in the type section; maximum 74 ft'): their span.
            vals = [_f(x.group(1)) * _unit_factor(x.group(2)) for x in found]
            return {"min_ft": min(vals), "max_ft": max(vals), "values_ft": vals,
                    "unit": found[0].group(2).lower().rstrip("."), "approximate": approx}
        m = found[0] if found else None
        if m:
            unit = m.group(2)
            lo = hi = _f(m.group(1)) * _unit_factor(unit)
        elif default_unit:
            nums = re.findall(_NUM, s)
            if not nums:
                return None
            unit = default_unit
            vals = [_f(n) * _unit_factor(default_unit) for n in nums[:2]]
            lo, hi = min(vals), max(vals)
        else:
            return None
    if lo == hi:
        if _UPPER.search(s):
            lo = None
        elif _LOWER.search(s):
            hi = None
    return {"min_ft": lo, "max_ft": hi, "unit": unit.lower().rstrip("."), "approximate": approx}


# --- soils -------------------------------------------------------------------

USCS = {"GW", "GP", "GM", "GC", "SW", "SP", "SM", "SC", "ML", "CL", "OL", "MH", "CH", "OH", "PT"}


def uscs(text) -> list[str]:
    tokens = re.findall(r"(?<![A-Za-z])([A-Z]{2})(?![a-z])", str(text or ""))
    return [t for t in tokens if t in USCS]


def spt_n(text) -> dict | None:
    """SPT N (blows per foot). '4-6-9' is three 6-inch increments: N = 6 + 9."""
    s = str(text or "").strip()
    if not s:
        return None
    if re.fullmatch(r"(?i)w\.?o\.?[hr]\.?|weight of (hammer|rods?)", s):
        return {"n": 0, "refusal": False}
    m = re.search(r"(\d+)\s*/\s*(\d+(?:\.\d+)?)\s*(\"|in)", s)
    if m:
        return {"n": int(m.group(1)), "refusal": True, "penetration_in": _f(m.group(2))}
    if re.search(r"(?i)\bref(usal|\.)?\b", s) and not re.search(r"\d", s):
        return {"n": None, "refusal": True}
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)(?:\s*-\s*(\d+))?", s)
    if m:
        return {"n": int(m.group(2)) + int(m.group(3)), "refusal": False,
                "increments": [int(g) for g in m.groups() if g is not None]}
    m = re.search(r"\d+", s)
    if not m:
        return None
    return {"n": int(m.group(0)), "refusal": bool(re.search(r"(?i)refus", s))}


# --- structure ---------------------------------------------------------------

_QUAD = re.compile(r"\b([NS])\s*(\d{1,2}(?:\.\d+)?)\s*°?\s*([EW])\b", re.I)
_DIP = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*°?\s*(NE|NW|SE|SW|N|S|E|W)?\b", re.I)


def _int(v: float):
    return int(v) if v == int(v) else v


def strike_dip(text) -> dict | None:
    s = str(text or "")
    m = _QUAD.search(s)
    if m:
        a = _f(m.group(2))
        ns, ew = m.group(1).upper(), m.group(3).upper()
        az = {("N", "E"): a, ("N", "W"): 360 - a, ("S", "E"): 180 - a, ("S", "W"): 180 + a}[(ns, ew)] % 360
        rest = s[m.end():]
        d = _DIP.search(rest)
        return {"strike": _int(az), "dip": _int(_f(d.group(1))) if d else None,
                "dip_direction": (d.group(2) or "").upper() or None if d else None, "convention_inferred": False}
    m = re.search(r"\b(\d{3})\s*°?\s*/\s*(\d{1,2})\b", s)
    if m:
        return {"strike": int(m.group(1)) % 360, "dip": int(m.group(2)), "dip_direction": None,
                "convention_inferred": True}
    m = re.search(r"(?i)strike\D{0,10}(\d{1,3})\D+?dip\D{0,10}(\d{1,2})\s*°?\s*(NE|NW|SE|SW|N|S|E|W)?", s)
    if m:
        return {"strike": int(m.group(1)) % 360, "dip": int(m.group(2)),
                "dip_direction": (m.group(3) or "").upper() or None, "convention_inferred": m.group(3) is None}
    return None


# --- coordinates -------------------------------------------------------------

# NAD83 South Carolina State Plane (FIPS 3900), Lambert conformal conic 2SP, GRS80.
_A = 6378137.0
_F = 1 / 298.257222101
_E = math.sqrt(2 * _F - _F * _F)
_LAT1, _LAT2, _LAT0, _LON0 = map(math.radians, (34 + 50 / 60, 32 + 30 / 60, 31 + 50 / 60, -81.0))
_FE_M, _FN_M = 609600.0, 0.0
FOOT = 0.3048
US_SURVEY_FOOT = 1200 / 3937


def _m(phi):
    return math.cos(phi) / math.sqrt(1 - (_E * math.sin(phi)) ** 2)


def _t(phi):
    es = _E * math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - es) / (1 + es)) ** (_E / 2)


_N = (math.log(_m(_LAT1)) - math.log(_m(_LAT2))) / (math.log(_t(_LAT1)) - math.log(_t(_LAT2)))
_FF = _m(_LAT1) / (_N * _t(_LAT1) ** _N)
_RHO0 = _A * _FF * _t(_LAT0) ** _N


def sc_state_plane_forward(lat: float, lon: float, unit: float = FOOT) -> tuple[float, float]:
    """(easting, northing) in `unit` (metres per unit; international foot by default)."""
    rho = _A * _FF * _t(math.radians(lat)) ** _N
    theta = _N * (math.radians(lon) - _LON0)
    return ((_FE_M + rho * math.sin(theta)) / unit, (_FN_M + _RHO0 - rho * math.cos(theta)) / unit)


def sc_state_plane_inverse(easting: float, northing: float, unit: float = FOOT) -> tuple[float, float]:
    """(lat, lon) in degrees from SC State Plane NAD83 easting/northing."""
    x, y = easting * unit - _FE_M, _RHO0 - (northing * unit - _FN_M)
    rho = math.copysign(math.hypot(x, y), _N)
    t = (rho / (_A * _FF)) ** (1 / _N)
    lon = math.atan2(x, y) / _N + _LON0
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(15):
        es = _E * math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan(t * ((1 - es) / (1 + es)) ** (_E / 2))
    return math.degrees(phi), math.degrees(lon)


_DMS = re.compile(r"(\d{1,3})\s*(?:°|º|deg\.?|\s)\s*(\d{1,2}(?:\.\d+)?)\s*(?:'|′|’|min\.?|\s)\s*"
                  r"(?:(\d{1,2}(?:\.\d+)?)\s*(?:\"|″|''|”|sec\.?)?)?\s*([NSEW])?", re.I)


def _sign_lon(lon: float, hemi: str | None) -> tuple[float, bool]:
    if hemi:
        return (-abs(lon) if hemi.upper() == "W" else abs(lon)), False
    if lon > 0 and 75 <= lon <= 85:  # South Carolina is west of Greenwich
        return -lon, True
    return lon, False


def _latlon(a: float, ha: str | None, b: float, hb: str | None) -> tuple[float, float, bool]:
    # Latitude is the one in SC's latitude band or tagged N/S.
    if (ha and ha.upper() in "EW") or (hb and hb.upper() in "NS") or (abs(a) > 60 and abs(b) < 60):
        a, ha, b, hb = b, hb, a, ha
    lat = -abs(a) if ha and ha.upper() == "S" else a
    lon, inferred = _sign_lon(b, hb)
    return lat, lon, inferred


def coordinates(text) -> dict | None:
    """Decimal degrees, DMS, or SC State Plane (NAD83, international feet unless stated) to lat/lon."""
    s = str(text or "")
    e = re.search(rf"(?i)(?:\bE\b|easting|\bx\b)\s*[:=]?\s*({_NUM})", s)
    n = re.search(rf"(?i)(?:\bN\b|northing|\by\b)\s*[:=]?\s*({_NUM})", s)
    plane = re.search(r"(?i)state\s*plane|spcs|fips\s*3900", s)
    if e and n and (plane or (_f(e.group(1)) >= 10000 and _f(n.group(1)) >= 10000)):
        if re.search(r"(?i)survey\s*f(ee|oo)t|us\s*ft|usft", s):
            unit, label = US_SURVEY_FOOT, "us_survey_ft"
        elif re.search(rf"(?i)({_NUM})\s*(m|meters?|metres?)\b", s):
            unit, label = 1.0, "m"
        else:
            unit, label = FOOT, "ft"
        lat, lon = sc_state_plane_inverse(_f(e.group(1)), _f(n.group(1)), unit)
        return {"lat": lat, "lon": lon, "format": "sc_state_plane", "unit": label,
                "datum_inferred": not re.search(r"(?i)nad\s*83", s), "hemisphere_inferred": False}
    if re.search(r"[°º′'″\"]|\bdeg", s) or re.search(r"\d+\s+\d+\s+\d+(?:\.\d+)?\s*[NS]\b", s):
        parts = [m for m in _DMS.finditer(s) if m.group(2) is not None]
        if len(parts) >= 2:
            vals = []
            for m in parts[:2]:
                v = int(m.group(1)) + _f(m.group(2)) / 60 + (_f(m.group(3)) / 3600 if m.group(3) else 0)
                vals.append((v, m.group(4)))
            lat, lon, inf = _latlon(vals[0][0], vals[0][1], vals[1][0], vals[1][1])
            return {"lat": lat, "lon": lon, "format": "dms", "hemisphere_inferred": inf}
    nums = list(re.finditer(r"(-?\d{1,3}\.\d+)\s*°?\s*([NSEW])?", s))
    if len(nums) >= 2:
        a, b = nums[0], nums[1]
        lat, lon, inf = _latlon(float(a.group(1)), a.group(2), float(b.group(1)), b.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return {"lat": lat, "lon": lon, "format": "decimal", "hemisphere_inferred": inf}
    return None


# --- ages and names ----------------------------------------------------------

def age_ma(text) -> dict | None:
    r = age_range(str(text or ""))
    if r is None:
        return None
    return {"younger_ma": r[0], "older_ma": r[1], "inferred": True, "source": AGE_SOURCE}


def unit_name(text, lexicon: Lexicon) -> dict | None:
    entry = lexicon.resolve(str(text or ""))
    if entry:
        return {"canonical": entry["name"], "in_geolex": True, "inferred": True}
    key = name_key(str(text or ""))[0]
    if key:
        return {"canonical": key, "in_geolex": False, "inferred": True}
    return None


# --- numbers and dates -------------------------------------------------------

def number(text) -> float | None:
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    m = re.search(rf"-?(?:{_NUM})", str(text or ""))
    return _f(m.group(0)) if m else None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def date(text) -> str | None:
    s = str(text or "").strip()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", s)
    if m:
        y = int(m.group(3))
        y = y + 1900 if y < 100 else y
        return f"{y:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(?:(\d{1,2}),?\s+)?(\d{4})\b", s)
    if m and m.group(1).lower() in _MONTHS:
        mo = _MONTHS[m.group(1).lower()]
        return f"{m.group(3)}-{mo:02d}-{int(m.group(2)):02d}" if m.group(2) else f"{m.group(3)}-{mo:02d}"
    return None
