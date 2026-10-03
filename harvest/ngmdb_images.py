"""NGMDB browse images as a full-text source for map sheets with no PDF.

Many NGMDB product pages (most SCGS 1:24,000 quadrangle maps) show the map
as a zoomable image but offer no download. The viewer loads it as a Zoomify
tile set:

    https://ngmdb.usgs.gov/img2/<range>/<id>_<n>/ImageProperties.xml
    https://ngmdb.usgs.gov/img2/<range>/<id>_<n>/TileGroup<g>/<z>-<x>-<y>.jpg

This module downloads the tiles of one tier (full resolution by default) and
assembles them, without decoding, into a one-page PDF (JPEG tiles placed as
DCTDecode images, 0.5 pt per pixel, i.e. 144 dpi). One image becomes one
page; extract/pdftext.py then OCRs it like any scanned page. Images, tiles
and PDFs stay in the gitignored .cache. The image URL (without the tile
part) is kept as the file URL and becomes the locator of every value read
from it (extract/ingest.py).

NGMDB's robots.txt disallows /img1/, /img2/ and /img4/ for crawlers; see
extract/README.md for why and how this is limited (fallback only, allowed
providers only, rate-limited, configurable in config/extract.json).
"""

from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

NGMDB = "https://ngmdb.usgs.gov"
SCALE = 0.5  # PDF points per image pixel (144 dpi): keeps sheets far below the 14,400 pt page limit
_HOLDINGS = re.compile(r"var holdings\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def browse_images(page: str, providers: list[str]) -> list[str]:
    """Image base URLs for sheets that have no PDF download, from the allowed providers."""
    m = _HOLDINGS.search(page or "")
    if not m:
        return []
    try:
        h = json.loads(m.group(1))
    except ValueError:
        return []
    out = []
    for img in h.get("images", []):
        fmts = {str(d.get("fmt")) for d in img.get("downloads", [])}
        if img.get("img") and not fmts & {"2", "3"} and img.get("provider") in providers:
            out.append(NGMDB + img["img"])
    return out


def image_properties(xml: str) -> dict:
    attr = dict(re.findall(r'(\w+)="([^"]*)"', xml or ""))
    if "WIDTH" not in attr or "HEIGHT" not in attr:
        raise ValueError("not a Zoomify ImageProperties.xml")
    return {"width": int(attr["WIDTH"]), "height": int(attr["HEIGHT"]), "tile_size": int(attr.get("TILESIZE", 256)),
            "num_tiles": int(attr["NUMTILES"]) if "NUMTILES" in attr else None}


def _sizes(w: int, h: int, ts: int = 256) -> list[tuple[int, int]]:
    sizes = [(w, h)]
    while w > ts or h > ts:
        w, h = w // 2, h // 2
        sizes.append((w, h))
    return sizes[::-1]  # smallest tier first, as Zoomify numbers them


def tiers(w: int, h: int, ts: int = 256) -> list[tuple[int, int]]:
    """(columns, rows) of tiles per tier, smallest first."""
    return [(math.ceil(a / ts), math.ceil(b / ts)) for a, b in _sizes(w, h, ts)]


def tile_size(w: int, h: int, z: int, x: int, y: int, ts: int = 256) -> tuple[int, int]:
    tw, th = _sizes(w, h, ts)[z]
    return min(ts, tw - x * ts), min(ts, th - y * ts)


def tile_url(base: str, w: int, h: int, z: int, x: int, y: int, ts: int = 256) -> str:
    t = tiers(w, h, ts)
    index = sum(c * r for c, r in t[:z]) + y * t[z][0] + x
    return f"{base}/TileGroup{index // 256}/{z}-{x}-{y}.jpg"


def jpeg_size(data: bytes) -> tuple[int, int, int]:
    """(width, height, components) from a JPEG's start-of-frame marker."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in _SOF:
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h, data[i + 9]
        i += 2 + length
    raise ValueError("JPEG has no frame header")


def build_pdf(base: str, dest: Path, fetcher, tier_offset: int = 0, workers: int = 4) -> Path:
    """Download one tier of an image's tiles and write them as a one-page PDF at dest."""
    props = image_properties(fetcher.text(base + "/ImageProperties.xml"))
    w, h, ts = props["width"], props["height"], props["tile_size"]
    t = tiers(w, h, ts)
    z = max(0, len(t) - 1 - tier_offset)
    cols, rows = t[z]
    zw, zh = _sizes(w, h, ts)[z]
    coords = [(x, y) for y in range(rows) for x in range(cols)]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        tiles = list(pool.map(lambda c: fetcher.bytes(tile_url(base, w, h, z, c[0], c[1], ts)), coords))

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    n = len(tiles)
    # Objects: 1 catalog, 2 pages, 3 page, 4 content, 5.. images.
    content = []
    for k, ((x, y), data) in enumerate(zip(coords, tiles)):
        iw, ih, _ = jpeg_size(data)
        tw, th = tile_size(w, h, z, x, y, ts)
        px, py = x * ts * SCALE, (zh - y * ts - th) * SCALE
        content.append(f"q {tw * SCALE:.2f} 0 0 {th * SCALE:.2f} {px:.2f} {py:.2f} cm /I{k} Do Q")
    stream = "\n".join(content).encode()
    xobjects = " ".join(f"/I{k} {5 + k} 0 R" for k in range(n))
    offsets = []
    with open(tmp, "wb") as f:
        def obj(num: int, body: bytes, data: bytes | None = None) -> None:
            offsets.append(f.tell())
            f.write(f"{num} 0 obj\n".encode() + body)
            if data is not None:
                f.write(b"\nstream\n" + data + b"\nendstream")
            f.write(b"\nendobj\n")

        f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
        obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
        obj(3, (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {zw * SCALE:.2f} {zh * SCALE:.2f}] "
                f"/Resources << /XObject << {xobjects} >> >> /Contents 4 0 R >>").encode())
        obj(4, f"<< /Length {len(stream)} >>".encode(), stream)
        for k, data in enumerate(tiles):
            iw, ih, comps = jpeg_size(data)
            space = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}.get(comps, "/DeviceRGB")
            obj(5 + k, (f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} /ColorSpace {space} "
                        f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>").encode(), data)
        xref = f.tell()
        f.write(f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode())
        for off in offsets:
            f.write(f"{off:010d} 00000 n \n".encode())
        f.write(f"trailer\n<< /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    tmp.replace(dest)
    return dest
