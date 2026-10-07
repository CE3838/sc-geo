"""A small GeoTIFF writer for tests: float32 grids laid out like PROJ-data vertical offset grids.

Written from the TIFF 6.0 and GeoTIFF 1.1 specifications (and libtiff's floating-point
predictor), independently of model/vdatum.py's reader, so tests check the reader against the
format rather than against itself.
"""

from __future__ import annotations

import struct
import zlib


def _fp_predict(row: bytes, width: int, bps: int = 4) -> bytes:
    """TIFF predictor 3: byte planes (most significant first), then horizontal byte differences."""
    planes = bytearray(width * bps)
    for i in range(width):
        be = row[i * bps:(i + 1) * bps]  # big-endian sample bytes
        for k in range(bps):
            planes[k * width + i] = be[k]
    out = bytearray(planes)
    for j in range(len(out) - 1, 0, -1):
        out[j] = (planes[j] - planes[j - 1]) & 0xFF
    return bytes(out)


def write(path, rows: list[list[float]], west: float, north: float, dx: float, dy: float, *,
          pixel_is_point: bool = True, nodata: float | None = None, compression: int = 1, predictor: int = 1,
          tile: int | None = None, byteorder: str = "<") -> None:
    """rows: north to south. (west, north) is the centre of the first pixel."""
    h, w = len(rows), len(rows[0])
    e = byteorder

    def block(r0, c0, bh, bw):
        data = bytearray()
        for r in range(r0, r0 + bh):
            vals = [(rows[r][c] if r < h and c < w else 0.0) for c in range(c0, c0 + bw)]
            if predictor == 3:
                data += _fp_predict(struct.pack(f">{bw}f", *vals), bw)
            else:
                data += struct.pack(f"{e}{bw}f", *vals)
        return zlib.compress(bytes(data)) if compression == 8 else bytes(data)

    if tile:
        blocks = [block(r, c, tile, tile) for r in range(0, h, tile) for c in range(0, w, tile)]
    else:
        blocks = [block(r, 0, 1, w) for r in range(h)]  # one row per strip

    if pixel_is_point:
        tie_x, tie_y, raster_type = west, north, 2
    else:
        tie_x, tie_y, raster_type = west - dx / 2, north + dy / 2, 1
    geokeys = [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, raster_type, 2048, 0, 1, 4269]
    tags = [(256, 3, [w]), (257, 3, [h]), (258, 3, [32]), (259, 3, [compression]), (262, 3, [1]),
            (277, 3, [1]), (317, 3, [predictor]), (339, 3, [3]),
            (33550, 12, [dx, dy, 0.0]), (33922, 12, [0.0, 0.0, 0.0, tie_x, tie_y, 0.0]), (34735, 3, geokeys)]
    if tile:
        tags += [(322, 3, [tile]), (323, 3, [tile]), (324, 4, [0] * len(blocks)), (325, 4, [len(b) for b in blocks])]
    else:
        tags += [(273, 4, [0] * len(blocks)), (278, 3, [1]), (279, 4, [len(b) for b in blocks])]
    if nodata is not None:
        tags.append((42113, 2, (repr(nodata) + "\0").encode()))
    tags.sort()

    size = {2: 1, 3: 2, 4: 4, 12: 8}
    fmt = {3: "H", 4: "I", 12: "d"}
    ifd_off = 8
    ifd_len = 2 + 12 * len(tags) + 4
    extra_off = ifd_off + ifd_len
    extra = bytearray()
    entries = []
    offsets_tag = 324 if tile else 273
    data_start = None
    # Lay out: header, IFD, out-of-line tag values, then image blocks.
    for tag, typ, vals in tags:
        count = len(vals)
        raw = bytes(vals) if typ == 2 else struct.pack(f"{e}{count}{fmt[typ]}", *vals)
        entries.append([tag, typ, count, raw])
    for ent in entries:
        if len(ent[3]) > 4:
            ent.append(extra_off + len(extra))
            extra += ent[3] + (b"\0" if len(ent[3]) % 2 else b"")
        else:
            ent.append(None)
    data_start = extra_off + len(extra)
    offs, pos = [], data_start
    for b in blocks:
        offs.append(pos)
        pos += len(b)
    for ent in entries:  # now that block offsets are known
        if ent[0] == offsets_tag:
            ent[3] = struct.pack(f"{e}{len(offs)}I", *offs)
            if ent[4] is not None:
                extra[ent[4] - extra_off:ent[4] - extra_off + len(ent[3])] = ent[3]
    out = bytearray((b"II" if e == "<" else b"MM") + struct.pack(f"{e}HI", 42, ifd_off))
    out += struct.pack(f"{e}H", len(entries))
    for tag, typ, count, raw, off in entries:
        out += struct.pack(f"{e}HHI", tag, typ, count)
        out += raw.ljust(4, b"\0") if off is None else struct.pack(f"{e}I", off)
    out += struct.pack(f"{e}I", 0)
    out += extra
    for b in blocks:
        out += b
    with open(path, "wb") as f:
        f.write(bytes(out))
