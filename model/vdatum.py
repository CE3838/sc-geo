"""Vertical datums: elevations to NAVD88.

NGVD29 -> NAVD88 uses the official NGS VERTCON shift grid as PROJ distributes it
(GeoTIFF, metres, NAVD88 minus NGVD29; see config/extract.json `vertical_datum`
and harvest/vertcon.py, which downloads it once into .cache/grids/). This module
reads that GeoTIFF with the standard library (TIFF 6.0 strips or tiles, no or
Deflate compression, horizontal or floating-point predictor, GeoTIFF tiepoint and
pixel scale, PixelIsPoint or PixelIsArea) and interpolates bilinearly.

Rules (`to_navd88`):

* NAVD88: unchanged.
* NGVD29: shifted by the grid at the value's location. Without a location, or
  outside the grid, there is no conversion. Without the grid there is none
  either, unless config sets `fallback_ngvd29_to_navd88_ft` (a cited constant):
  then the shift is that constant, marked approximate.
* "Sea level"/MSL: read as NGVD29 only for documents published before
  `msl_as_ngvd29_before` (1991, when NAVD88 came into use), marked
  approximate; later documents get no conversion (the datum is unclear).
* Land surface: stays relative; no conversion.
* Not stated / unknown: kept as it is, marked approximate.

Every result says what it assumed. Callers store it flagged inferred.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

FOOT = 0.3048


@dataclass
class ShiftGrid:
    west: float      # longitude of the first column's pixel centre
    north: float     # latitude of the first row's pixel centre
    dx: float
    dy: float
    ncols: int
    nrows: int
    values: list[float]  # row-major, north to south
    nodata: float | None = None
    name: str = ""

    def shift_m(self, lat: float, lon: float) -> float | None:
        """Bilinear shift in metres, or None outside the grid or next to a nodata cell."""
        for x in (lon, lon + 360, lon - 360):
            fx = (x - self.west) / self.dx
            if -1e-9 <= fx <= self.ncols - 1 + 1e-9:
                break
        else:
            return None
        fy = (self.north - lat) / self.dy
        if not -1e-9 <= fy <= self.nrows - 1 + 1e-9:
            return None
        fx, fy = min(max(fx, 0.0), self.ncols - 1), min(max(fy, 0.0), self.nrows - 1)
        c0, r0 = min(int(fx), self.ncols - 2), min(int(fy), self.nrows - 2)
        tx, ty = fx - c0, fy - r0
        corners = []
        for r in (r0, r0 + 1):
            for c in (c0, c0 + 1):
                v = self.values[r * self.ncols + c]
                if math.isnan(v) or (self.nodata is not None and v == self.nodata):
                    return None
                corners.append(v)
        a, b, c, d = corners
        return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty


# --- GeoTIFF -------------------------------------------------------------------

_TYPES = {1: ("B", 1), 2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 11: ("f", 4), 12: ("d", 8), 16: ("Q", 8)}


def _undo_fp_predictor(buf: bytes, width: int, rows: int, bps: int) -> list[float]:
    out = []
    rowlen = width * bps
    fmt = {4: ">f", 8: ">d"}[bps]
    for r in range(rows):
        row = bytearray(buf[r * rowlen:(r + 1) * rowlen])
        for j in range(1, rowlen):
            row[j] = (row[j] + row[j - 1]) & 0xFF
        for i in range(width):
            out.append(struct.unpack(fmt, bytes(row[k * width + i] for k in range(bps)))[0])
    return out


def _decode(buf: bytes, width: int, rows: int, bps: int, predictor: int, order: str) -> list[float]:
    if predictor == 3:
        return _undo_fp_predictor(buf, width, rows, bps)
    if predictor != 1:
        raise ValueError(f"unsupported TIFF predictor {predictor} for floating-point data")
    n = width * rows
    return list(struct.unpack(f"{order}{n}{'f' if bps == 4 else 'd'}", buf[:n * bps]))


def read_geotiff(path) -> ShiftGrid:
    data = Path(path).read_bytes()
    if data[:4] not in (b"II*\0", b"MM\0*"):
        raise ValueError(f"{path} is not a classic TIFF file")
    e = "<" if data[:2] == b"II" else ">"
    (ifd,) = struct.unpack(f"{e}I", data[4:8])
    (count,) = struct.unpack(f"{e}H", data[ifd:ifd + 2])
    tags: dict[int, list] = {}
    for i in range(count):
        tag, typ, n = struct.unpack(f"{e}HHI", data[ifd + 2 + 12 * i:ifd + 10 + 12 * i])
        if typ not in _TYPES:
            continue
        code, size = _TYPES[typ]
        raw_off = ifd + 10 + 12 * i
        if n * size > 4:
            (raw_off,) = struct.unpack(f"{e}I", data[raw_off:raw_off + 4])
        raw = data[raw_off:raw_off + n * size]
        tags[tag] = [raw.rstrip(b"\0").decode("ascii", "replace")] if typ == 2 else list(struct.unpack(f"{e}{n}{code}", raw))
    width, height = tags[256][0], tags[257][0]
    bps = tags.get(258, [8])[0]
    if tags.get(339, [1])[0] != 3 or bps not in (32, 64) or tags.get(277, [1])[0] != 1:
        raise ValueError(f"{path}: expected one band of 32- or 64-bit floats")
    bps //= 8
    compression, predictor = tags.get(259, [1])[0], tags.get(317, [1])[0]
    if compression not in (1, 8, 32946):
        raise ValueError(f"{path}: unsupported TIFF compression {compression}")

    def block(off, length):
        b = data[off:off + length]
        return zlib.decompress(b) if compression in (8, 32946) else b

    values = [float("nan")] * (width * height)
    if 322 in tags:
        tw, th = tags[322][0], tags[323][0]
        across = (width + tw - 1) // tw
        for k, (off, length) in enumerate(zip(tags[324], tags[325])):
            tile = _decode(block(off, length), tw, th, bps, predictor, e)
            r0, c0 = (k // across) * th, (k % across) * tw
            for r in range(th):
                if r0 + r >= height:
                    break
                for c in range(tw):
                    if c0 + c < width:
                        values[(r0 + r) * width + c0 + c] = tile[r * tw + c]
    else:
        rps = tags.get(278, [height])[0]
        for k, (off, length) in enumerate(zip(tags[273], tags[279])):
            rows = min(rps, height - k * rps)
            values[k * rps * width:(k * rps + rows) * width] = _decode(block(off, length), width, rows, bps, predictor, e)
    sx, sy = tags[33550][0], tags[33550][1]
    tie = tags[33922]
    i, j, x, y = tie[0], tie[1], tie[3], tie[4]
    keys = tags.get(34735, [])
    point = any(keys[n] == 1025 and keys[n + 3] == 2 for n in range(4, len(keys) - 3, 4))
    west, north = x - i * sx, y + j * sy
    if not point:  # PixelIsArea: the tiepoint is the corner of the pixel
        west, north = west + sx / 2, north - sy / 2
    nodata = float(tags[42113][0]) if 42113 in tags and tags[42113][0].strip() else None
    return ShiftGrid(west, north, sx, sy, width, height, values, nodata, Path(path).name)


def load_grid(path) -> ShiftGrid | None:
    p = Path(path)
    return read_geotiff(p) if p.exists() else None


# --- conversion ----------------------------------------------------------------

def to_navd88(ft: dict, datum: str | None, lat: float | None, lon: float | None, year: int | None,
              grid: ShiftGrid | None, cfg: dict) -> tuple[dict | None, str | None]:
    """({'min_ft', 'max_ft', 'from_datum', 'shift_ft', 'conversion', 'approximate', 'assumptions'}, None)
    or (None, reason). `ft` is a normalized length or elevation ({'min_ft', 'max_ft'}, either open)."""
    assumptions: list[str] = []
    approximate = False
    if datum == "land surface":
        return None, "relative to land surface; no elevation datum"
    if datum == "MSL":
        cutoff = cfg.get("msl_as_ngvd29_before", 1991)
        if not year or year >= cutoff:
            return None, f"sea level in a document from {year or 'an unknown year'}: NGVD29 or NAVD88 unclear"
        assumptions.append(f"sea level read as NGVD29 (document published {year}, before NAVD88)")
        approximate = True
        datum = "NGVD29"
    if datum == "NAVD88":
        shift, conversion = 0.0, "none (already NAVD88)"
    elif datum == "NGVD29":
        fallback = cfg.get("fallback_ngvd29_to_navd88_ft")
        if grid is None and fallback is None:
            return None, "no NGVD29-to-NAVD88 grid; run python -m harvest.vertcon"
        if grid is None:
            shift = float(fallback)
            approximate = True
            conversion = f"NGVD29 to NAVD88 by a constant {fallback:+} ft ({cfg.get('fallback_source') or 'configured'})"
        else:
            if lat is None or lon is None:
                return None, "NGVD29 value without a location; the shift varies by place"
            m = grid.shift_m(lat, lon)
            if m is None:
                return None, f"location outside the {grid.name or 'shift'} grid"
            shift = m / FOOT
            conversion = f"NGVD29 to NAVD88 by the {grid.name or 'VERTCON'} grid (bilinear)"
    elif datum in (None, "unknown"):
        shift, conversion = 0.0, "none (datum not stated)"
        approximate = True
        assumptions.append("vertical datum not stated; kept as printed (NGVD29 and NAVD88 differ by about a foot here)")
        return {"min_ft": ft.get("min_ft"), "max_ft": ft.get("max_ft"), "from_datum": None, "shift_ft": 0.0,
                "conversion": conversion, "approximate": True, "assumptions": assumptions}, None
    else:
        return None, f"datum {datum!r} not supported"
    add = lambda v: None if v is None else v + shift
    return {"min_ft": add(ft.get("min_ft")), "max_ft": add(ft.get("max_ft")), "from_datum": datum,
            "shift_ft": shift, "conversion": conversion, "approximate": approximate, "assumptions": assumptions}, None
