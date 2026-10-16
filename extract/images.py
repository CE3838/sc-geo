"""Page images for reading what the text layer garbles: map faces, cross sections, logs drawn as figures.

    python -m extract.images ngmdb:100312 --pages 1                       # overview + tiles at the default dpi
    python -m extract.images ngmdb:100312 --pages 1 --dpi 250 --grid 3x3  # COLSxROWS tiles
    python -m extract.images ngmdb:100312 --pages 1 --crop 0,1900,2100,2700   # one region (PDF points)
    python -m extract.images ngmdb:100312 --pages 1 --reread --reason "section A-A' distances and elevations"

Pages are rendered from the cached PDF only (.cache/pdfs, never downloaded:
with nothing cached, get it with `python -m harvest.pdfs --id <ID>`) with
pdftoppm into PNG tiles in .cache/images/<id>/ (never committed, CLAUDE.md
rule 3). Each request writes an overview of the whole page (for finding the
sections, the legend and the scale) and overlapping tiles no larger than
`images.max_tile_px` (config/extract.json), so the Read tool shows them at
full resolution. A scan is never rendered above its own resolution.

`manifest.json` lists every tile: its page, the page of its file, dpi, its
box in page pixels at that dpi and in PDF points (from the page's top-left
corner), its size and the file's sha256. Tiles already rendered are never
rendered again, so the command is resumable and cheap to repeat.

A value read from a tile cites it in the result (`"image": {"tile": ..., "box":
[x0, y0, x1, y1]}`, the box in the tile's pixels). `extract.ingest` stores such
a value with extraction_method "llm-image" and a locator naming the source
file, page and box in points (`#page=N&viewrect=left,top,width,height`) when
its quote is not in the page text; see extract/README.md, Page images.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from extract import pdftext
from extract.packets import safe_id

ROOT = Path(__file__).resolve().parent.parent
CONFIG: dict = json.loads((ROOT / "config" / "extract.json").read_text())
CACHE = ROOT / ".cache"
SETTINGS = CONFIG["images"]

# Values whose position is read off a drawing are inferred whatever the reader says (CLAUDE.md rule 2).
_DRAWN = re.compile(r"^sections\[\d+\]\.contacts\[\d+\]\.points\[")
_DRAWN_IF_IMAGE = re.compile(r"^sections\[\d+\]\.holes\[\d+\]\.distance$")


class ImagesError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_grid(text: str) -> tuple[int, int]:
    """'3x2' -> (3 columns, 2 rows)."""
    m = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", text or "")
    if not m or not int(m.group(1)) or not int(m.group(2)):
        raise ImagesError(f"grid {text!r} is not COLSxROWS, e.g. 3x3")
    return int(m.group(1)), int(m.group(2))


def parse_box(text: str) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(v) for v in text.split(","))
    except ValueError:
        raise ImagesError(f"box {text!r} is not x0,y0,x1,y1") from None
    if x1 <= x0 or y1 <= y0:
        raise ImagesError(f"box {text!r} is empty")
    return x0, y0, x1, y1


def _spans(length: int, n: int | None, max_px: int, overlap: int) -> list[tuple[int, int]]:
    """n (or as few as fit max_px) spans covering 0..length, neighbours overlapping by `overlap`."""
    if n is None:
        n = 1 if length <= max_px else math.ceil((length - overlap) / max(1, max_px - overlap))
    n = max(1, n)
    size = min(length, math.ceil((length + (n - 1) * overlap) / n))
    starts = [0] if n == 1 else [round(i * (length - size) / (n - 1)) for i in range(n)]
    return [(s, min(length, s + size)) for s in starts]


def plan_grid(width_px: int, height_px: int, cols: int | None = None, rows: int | None = None,
              max_tile_px: int = SETTINGS["max_tile_px"], overlap_px: int = SETTINGS["overlap_px"]) -> list[dict]:
    """Overlapping tiles covering a width x height pixel area, row by row ({row, col, px_box})."""
    xs = _spans(width_px, cols, max_tile_px, overlap_px)
    ys = _spans(height_px, rows, max_tile_px, overlap_px)
    return [{"row": r, "col": c, "px_box": [x0, y0, x1, y1]}
            for r, (y0, y1) in enumerate(ys, 1) for c, (x0, x1) in enumerate(xs, 1)]


def estimated_tokens(w: int, h: int) -> int:
    """Image tokens as the Read tool sends them (about w*h/750, after scaling the long side to view_px)."""
    s = min(1.0, SETTINGS["view_px"] / max(w, h, 1))
    return math.ceil(w * s * h * s / 750)


# --- poppler -----------------------------------------------------------------------------------

def page_size(pdf: Path, n: int) -> tuple[float, float]:
    """(width, height) of page n in PDF points as rendered (rotation applied), from pdfinfo."""
    out = subprocess.run(["pdfinfo", "-f", str(n), "-l", str(n), str(pdf)], capture_output=True, text=True,
                         timeout=120, check=True).stdout
    m = re.search(rf"Page\s+{n}\s+size:\s*([\d.]+)\s*x\s*([\d.]+)", out)
    if not m:
        raise ImagesError(f"pdfinfo gives no size for page {n} of {pdf}")
    w, h = float(m.group(1)), float(m.group(2))
    rot = re.search(rf"Page\s+{n}\s+rot:\s*(\d+)", out)
    return (h, w) if rot and int(rot.group(1)) % 180 == 90 else (w, h)


def _pdftoppm(pdf: Path, n: int, dpi: float, box: list[int], out: Path) -> None:
    x0, y0, x1, y1 = box
    stem = out.with_suffix("")
    subprocess.run(["pdftoppm", "-r", f"{dpi:g}", "-f", str(n), "-l", str(n), "-x", str(x0), "-y", str(y0),
                    "-W", str(x1 - x0), "-H", str(y1 - y0), "-png", "-singlefile", str(pdf), str(stem)],
                   capture_output=True, timeout=SETTINGS["render_timeout_seconds"], check=True)


def _native_ppi(pdf: Path, n: int) -> int | None:
    return pdftext.native_dpi(pdf, n)


# --- rendering ---------------------------------------------------------------------------------

def load_manifest(sid: str, images_dir: Path | None = None) -> dict | None:
    path = Path(images_dir or CACHE / "images") / safe_id(sid) / "manifest.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _pdf_for(doc: dict, page: dict, cache_dir: Path, sid: str) -> tuple[int, dict, Path]:
    idx = page.get("file", 0)
    f = doc["files"][idx]
    candidates = [Path(f["path"])] if f.get("path") else []
    candidates.append(cache_dir / "pdfs" / safe_id(sid) / f"{idx + 1:02d}.pdf")
    for p in candidates:
        if p.exists():
            return idx, f, p
    raise ImagesError(f"page {page['page']} of {sid}: the PDF is not cached ({candidates[0]}); images are made "
                      f"from the cached PDF only. Get it with python -m harvest.pdfs --id {sid}")


def _scan(doc: dict, page: dict) -> bool:
    f = doc["files"][page.get("file", 0)]
    return page.get("method") == "ocr" or f.get("via") in ("ngmdb_scan", "ngmdb_image")


def render(sid: str, pages: list[int], dpi: float | None = None, grid: tuple[int, int] | None = None,
           crop: tuple[float, float, float, float] | None = None, overview: bool = True, cache_dir: Path = CACHE,
           renderer: Callable | None = None, sizer: Callable | None = None, native: Callable | None = None) -> dict:
    """Render an overview and tiles of chosen pages from the cached PDF; returns this request's tiles.

    grid is (columns, rows); without it, tiles are as few as keep each under images.max_tile_px. crop is a box
    in PDF points (x0, y0, x1, y1 from the page's top-left corner): only that region is tiled."""
    cache_dir = Path(cache_dir)
    renderer = renderer or _pdftoppm
    sizer = sizer or page_size
    native = native or _native_ppi
    safe = safe_id(sid)
    text_path = cache_dir / "text" / f"{safe}.json"
    if not text_path.exists():
        raise ImagesError(f"no cached text for {sid} at {text_path}, so no cached PDF is known; images never "
                          f"download. Get it with python -m harvest.pdfs --id {sid}")
    doc = json.loads(text_path.read_text())
    by_page = {p["page"]: p for p in doc["pages"]}
    unknown = [n for n in pages if n not in by_page]
    if unknown:
        raise ImagesError(f"{sid} has no page {', '.join(map(str, unknown))} (pages 1-{max(by_page)})")
    out_dir = cache_dir / "images" / safe
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(sid, cache_dir / "images") or {
        "source_id": sid,
        "about": "Page images rendered from the cached PDF by python -m extract.images (never committed). "
                 "px_box: pixels of the whole page at the tile's dpi; pt_box: PDF points from the page's "
                 "top-left corner; both [x0, y0, x1, y1].",
        "files": {}, "pages": {}, "tiles": {}}
    want = dpi or SETTINGS["dpi"]
    request: list[dict] = []
    for n in pages:
        page = by_page[n]
        idx, f, pdf = _pdf_for(doc, page, cache_dir, sid)
        if str(idx) not in manifest["files"]:
            manifest["files"][str(idx)] = {"url": f.get("url"), "path": str(pdf),
                                           "sha256": f.get("sha256") or pdftext.sha256(pdf)}
        fp = page.get("file_page", n)
        w_pt, h_pt = sizer(pdf, fp)
        ppi = native(pdf, fp) if _scan(doc, page) else None
        use = min(want, SETTINGS["max_dpi"], ppi) if ppi else min(want, SETTINGS["max_dpi"])
        use = round(use)
        size_px = [math.ceil(round(w_pt * use / 72, 6)), math.ceil(round(h_pt * use / 72, 6))]
        manifest["pages"][str(n)] = {"file": idx, "file_page": fp, "size_pt": [w_pt, h_pt], "dpi": use,
                                     "size_px": size_px, "native_ppi": ppi, "dpi_requested": want}
        jobs = []
        if overview:
            ov = SETTINGS["max_tile_px"] * 72 / max(w_pt, h_pt)
            ov_dpi = round(min(ov, use), 3)
            ov_px = [math.ceil(round(w_pt * ov_dpi / 72, 6)), math.ceil(round(h_pt * ov_dpi / 72, 6))]
            jobs.append({"tile": f"p{n}-overview-{ov_dpi:g}dpi", "kind": "overview", "dpi": ov_dpi,
                         "px_box": [0, 0, *ov_px], "row": 1, "col": 1})
        if crop:
            x0, y0, x1, y1 = crop
            box = [max(0, math.floor(x0 * use / 72)), max(0, math.floor(y0 * use / 72)),
                   min(size_px[0], math.ceil(x1 * use / 72)), min(size_px[1], math.ceil(y1 * use / 72))]
            if box[2] <= box[0] or box[3] <= box[1]:
                raise ImagesError(f"crop {crop} is outside page {n} ({w_pt:g} x {h_pt:g} pt)")
            name = f"p{n}-{use}dpi-crop{x0:g}_{y0:g}_{x1:g}_{y1:g}"
            for t in plan_grid(box[2] - box[0], box[3] - box[1], *(grid or (None, None))):
                b = t["px_box"]
                jobs.append({"tile": f"{name}-r{t['row']}c{t['col']}", "kind": "crop", "dpi": use, "row": t["row"],
                             "col": t["col"], "px_box": [b[0] + box[0], b[1] + box[1], b[2] + box[0], b[3] + box[1]]})
        else:
            tiles = plan_grid(size_px[0], size_px[1], *(grid or (None, None)))
            cols, rows = max(t["col"] for t in tiles), max(t["row"] for t in tiles)
            for t in tiles:
                jobs.append({"tile": f"p{n}-{use}dpi-{cols}x{rows}-r{t['row']}c{t['col']}", "kind": "tile",
                             "dpi": use, **t})
        for j in jobs:
            path = out_dir / f"{j['tile']}.png"
            known = manifest["tiles"].get(j["tile"])
            if not (known and path.exists() and known["px_box"] == j["px_box"]):
                try:
                    renderer(pdf, fp, j["dpi"], j["px_box"], path)
                except (OSError, subprocess.SubprocessError) as err:
                    raise ImagesError(f"pdftoppm failed on page {n} of {sid}: {err}") from None
                x0, y0, x1, y1 = j["px_box"]
                known = {**j, "file": path.name, "page": n, "file_index": idx, "file_page": fp,
                         "pt_box": [round(min(v * 72 / j["dpi"], lim), 2)
                                    for v, lim in zip(j["px_box"], [w_pt, h_pt, w_pt, h_pt])],
                         "size_px": [x1 - x0, y1 - y0], "estimated_tokens": estimated_tokens(x1 - x0, y1 - y0),
                         "rendered_at": _now()}
                manifest["tiles"][j["tile"]] = known
            request.append(known)
    manifest["updated_at"] = _now()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return {"source_id": sid, "manifest": str(out_dir / "manifest.json"), "dir": str(out_dir),
            "files": manifest["files"], "pages": {str(n): manifest["pages"][str(n)] for n in pages},
            "tiles": request, "estimated_tokens": sum(t["estimated_tokens"] for t in request)}


# --- locators and confidence --------------------------------------------------------------------

def resolve(manifest: dict, tile: str, box: list[float]) -> dict:
    """A box in a tile's pixels -> the tile's page, the box in page pixels and in PDF points."""
    t = (manifest or {}).get("tiles", {}).get(tile)
    if t is None:
        raise ImagesError(f"tile {tile!r} is not in the image manifest")
    if len(box) != 4:
        raise ImagesError(f"box {box} is not [x0, y0, x1, y1]")
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        raise ImagesError(f"box {box} is empty")
    w, h = t["size_px"]
    if min(box) < 0 or x1 > w or y1 > h:
        raise ImagesError(f"box {box} is outside tile {tile} ({w} x {h} px)")
    ox, oy = t["px_box"][:2]
    page_px = [ox + x0, oy + y0, ox + x1, oy + y1]
    f = manifest.get("files", {}).get(str(t.get("file_index", 0)), {})
    return {"tile": tile, "page": t["page"], "file_page": t.get("file_page", t["page"]), "dpi": t["dpi"],
            "box": list(box), "page_px_box": page_px, "pt_box": [round(v * 72 / t["dpi"], 2) for v in page_px],
            "url": f.get("url"), "pdf_sha256": f.get("sha256")}


def locator(base: str | None, r: dict) -> str:
    """'<file url>#page=N&viewrect=left,top,width,height' (PDF points of the cached PDF's page)."""
    left, top, right, bottom = r["pt_box"]
    rect = f"{left:g},{top:g},{round(right - left, 2):g},{round(bottom - top, 2):g}"
    return f"{base or 'pdf'}#page={r['file_page']}&viewrect={rect}"


def confidence(s: float, verdict: str | None, inferred: bool, unclear: bool, cfg: dict = CONFIG) -> float:
    """An image reading: min(images.confidence.max, S x factor) x V x I x U.

    The cap keeps every image reading below text-checked values; the verdict, an inference and digits
    marked unclear each lower it further."""
    c, ic = cfg["confidence"], cfg["images"]["confidence"]
    v = {"agree": c["verify_agree"], "disagree": c["verify_disagree"], "unclear": c["verify_unclear"],
         None: c["verify_unchecked"]}[verdict]
    base = min(ic["max"], s * ic["factor"])
    x = base * v * (c["inferred_factor"] if inferred else 1.0) * (ic["unclear_factor"] if unclear else 1.0)
    return round(min(ic["max"], max(0.0, x)), 3)


class IngestImages:
    """What extract.ingest does with values read from tiles (kept here so ingest only calls it)."""

    def __init__(self, sid: str, images_dir: Path, cfg: dict = CONFIG):
        self.sid, self.cfg, self.images_dir = sid, cfg, Path(images_dir)
        self._manifest: dict | None | bool = False

    @property
    def manifest(self) -> dict | None:
        if self._manifest is False:
            self._manifest = load_manifest(self.sid, self.images_dir)
        return self._manifest

    @staticmethod
    def prepare(path: str, val: dict) -> None:
        """Positions read off a drawing (section contact points, a hole's distance read from a tile) are inferred."""
        if _DRAWN.match(path) or (val.get("image") and _DRAWN_IF_IMAGE.match(path)):
            val["inferred"] = True

    def _info(self, val: dict, r: dict | None) -> dict:
        im = val["image"]
        out = {"tile": im["tile"], "box": im["box"]}
        if r:
            out |= {"dpi": r["dpi"], "page_px_box": r["page_px_box"], "pt_box": r["pt_box"],
                    "pdf_sha256": r["pdf_sha256"]}
        if im.get("unclear"):
            out["unclear"] = True
        return out

    def entry(self, path: str, val: dict, rec: dict, check: dict | None, counts: dict, queue: Callable,
              map_sheet: bool) -> dict | None:
        """The stored form of a value whose quote is not in the page text but on a tile; None when refused."""
        from extract.ingest import source_weight
        from model.provenance import ExtractionMethod, StoredValue

        def bump(key):
            counts[key] = counts.get(key, 0) + 1
        try:
            if self.manifest is None:
                raise ImagesError(f"no image manifest for {self.sid}; render the tiles with python -m extract.images "
                                  f"{self.sid} --pages {val['page']} before ingesting image values")
            r = resolve(self.manifest, val["image"]["tile"], val["image"]["box"])
            if r["page"] != val["page"]:
                raise ImagesError(f"tile {r['tile']} is page {r['page']}, the value cites page {val['page']}")
        except ImagesError as err:
            bump("image_locator_invalid")
            queue(path, val, "image_locator_invalid", detail=str(err), image=val["image"])
            return None
        verdict = check["verdict"] if check else None
        if verdict is None:
            bump("image_not_verified")
            queue(path, val, "image_not_verified", image=self._info(val, r),
                  detail="values read from an image are stored only after a verify pass re-views the tile")
            return None
        bump(verdict)
        if verdict in ("disagree", "unclear"):
            queue(path, val, f"verify_{verdict}", verify={k: v for k, v in check.items() if k != "path"})
        unclear = bool(val["image"].get("unclear"))
        if unclear:
            queue(path, val, "image_unclear", image=self._info(val, r))
        s = source_weight(rec, path.split("[", 1)[0], self.cfg, map_sheet)
        sv = StoredValue(value=val["value"], source_id=self.sid, page=val["page"],
                         extraction_method=ExtractionMethod.LLM_IMAGE,
                         confidence=confidence(s, verdict, bool(val["inferred"]), unclear, self.cfg),
                         inferred=bool(val["inferred"]), locator=locator(r["url"], r))
        entry = sv.to_dict() | {"quote": val["quote"], "quote_match": "image", "text_method": "image",
                                "verification": verdict, "image": self._info(val, r)}
        for k in ("units", "table", "note"):
            if k in val:
                entry[k] = val[k]
        bump("image")
        return entry

    def annotate(self, stored: dict, result: dict) -> None:
        """Values whose quote was found in the text keep the text check; they also keep the tile they cite."""
        from extract import schema
        for path, entry in stored.items():
            if entry.get("extraction_method") == "llm-image":
                continue
            val = schema.get_path(result, path)
            if isinstance(val, dict) and val.get("image"):
                try:
                    r = resolve(self.manifest, val["image"]["tile"], val["image"]["box"]) if self.manifest else None
                except ImagesError:
                    r = None
                entry["image"] = self._info(val, r)


# --- the command ---------------------------------------------------------------------------------

def _print(m: dict) -> None:
    print(f"manifest: {m['manifest']}")
    for n, p in m["pages"].items():
        note = f", scan {p['native_ppi']} ppi" if p.get("native_ppi") else ""
        print(f"page {n}: {p['size_pt'][0]:g} x {p['size_pt'][1]:g} pt, {p['dpi']} dpi "
              f"({p['size_px'][0]} x {p['size_px'][1]} px{note})")
    for t in m["tiles"]:
        print(f"view:  {Path(m['dir']) / t['file']}  ({t['tile']}, page {t['page']}, {t['size_px'][0]}x"
              f"{t['size_px'][1]} px, pt {t['pt_box']}, ~{t['estimated_tokens']:,} tokens)")
    print(f"~{m['estimated_tokens']:,} tokens for {len(m['tiles'])} images")


def main(argv: list[str] | None = None) -> int:
    from extract import reread
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("id", help="catalog id")
    ap.add_argument("--pages", required=True, help="pages to render, e.g. 1 or 1,3-4")
    ap.add_argument("--dpi", type=float, help=f"render resolution (default {SETTINGS['dpi']}; never above a scan's own)")
    ap.add_argument("--grid", help="COLSxROWS tiles, e.g. 3x3 (default: as few as fit max_tile_px)")
    ap.add_argument("--crop", help="only this region, x0,y0,x1,y1 in PDF points from the top-left corner")
    ap.add_argument("--no-overview", action="store_true", help="skip the whole-page overview")
    ap.add_argument("--reread", action="store_true",
                    help="also build a re-read packet of these pages that points to the tiles (extract.reread)")
    ap.add_argument("--reason", help="with --reread: why the pages are re-read")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        pages = reread.parse_pages(args.pages)
        opts = {"dpi": args.dpi, "grid": parse_grid(args.grid) if args.grid else None,
                "crop": parse_box(args.crop) if args.crop else None, "overview": not args.no_overview}
        if args.reread:
            batch = [reread.build(args.id, pages=pages, reason=args.reason or "read from page images",
                                  images=opts, cache_dir=CACHE)]
            if args.json:
                print(json.dumps(batch, indent=1, ensure_ascii=False))
            else:
                reread._print(batch)
            return 0
        m = render(args.id, pages, dpi=opts["dpi"], grid=opts["grid"], crop=opts["crop"], overview=opts["overview"],
                   cache_dir=CACHE)
    except (ImagesError, reread.RereadError) as err:
        print(f"images refused: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(m, indent=1))
    else:
        _print(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
