"""Re-read chosen pages of a document that was already read, from the cache only.

    python -m extract.reread ngmdb:42961 --pages 1 --reason "contour values on the map face"
    python -m extract.reread ngmdb:27394 --packets packet-02 --reason "new subsurface fields"
    python -m extract.reread ngmdb:96652 --pages 79-82 --ocr --reason "piezometer logs are images"
    python -m extract.reread ngmdb:100312 --pages 1 --images [--dpi 250 --grid 3x3] --reason "section A-A'"
    python -m extract.reread --next [--n 3] [--max-tokens 120000] [--json]   # next items of the re-read queue
    python -m extract.reread --queue                                          # rebuild data/review/reread_queue.json
    python -m extract.reread --add ngmdb:X --pages 4 --reason "OCR misread digits"   # add a queue item
    python -m extract.reread --add ngmdb:X --pages 11-18 --reason water_tests --detail "Tables 3-6: chemistry"

A re-read builds packets of exactly the chosen pages (triage is not asked)
in .cache/packets/<id>/reread/ (names reread-01, reread-02, ... never
reused), from the page text already in .cache/text. It never downloads:
with no cached text it stops and says so. `--ocr` OCRs the chosen pages
from the cached PDF (for image-only pages, or log pages whose text layer
holds only a caption), adds the OCR text to the page and marks it "ocr".

The result of a re-read is written, checked, verified and ingested exactly
like any packet result (`"packets": ["reread-01"]`). Ingest replaces every
value stored from those pages with the new reading; the values it replaces
go to the extracted file's `history` with the date and the reason, and the
review queue drops items for those pages and adds the new ones.

The re-read queue (data/review/reread_queue.json) lists what needs a
re-read: the "SUBSURFACE:" notes lines of data/extracted (documents with
cross sections, contours or tops noted but no subsurface values stored),
the known re-reads below, and items added with --add. An item is done once
an ingest records its queue id on all its pages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from extract import packets, pdftext, scope

ROOT = Path(__file__).resolve().parent.parent
CONFIG: dict = json.loads((ROOT / "config" / "extract.json").read_text())
CACHE = ROOT / ".cache"
EXTRACTED = ROOT / "data" / "extracted"
QUEUE_PATH = ROOT / "data" / "review" / "reread_queue.json"
SUBSURFACE_SECTIONS = ("surfaces", "contours", "sections")
# Queue items read from page images as well as text (extract/images.py): map faces, image-only pages,
# subsurface fields, and anything about cross sections.
IMAGE_REASONS = ("map_face", "image_pages", "subsurface_fields")
_SECTION_WORDS = re.compile(r"\bsections?\b|\b([A-H])\s*[-–]\s*\1\s*['′’]", re.I)


def wants_images(item: dict) -> bool:
    """Whether a re-read queue item calls for page images (an explicit "images" key wins)."""
    if "images" in item:
        return bool(item["images"])
    return item.get("reason") in IMAGE_REASONS or bool(_SECTION_WORDS.search(item.get("detail") or ""))

# Re-reads already known (ROADMAP 1.9). Pages are the document's page numbers (as cited in data/extracted).
KNOWN = [
    {"source_id": "ngmdb:74345", "pages": [18], "reason": "image_pages", "ocr": True,
     "detail": "Page 18 (figure) had no text and was not OCRed in the first reading."},
    {"source_id": "ngmdb:74350", "pages": [280, 281, 282, 300, 301], "reason": "image_pages", "ocr": True,
     "detail": "Pages 280-282, 300 and 301 were image-only and not OCRed in the first reading."},
    {"source_id": "ngmdb:27394", "pages": [6, 7, 12, 13, 14, 15, 19, 20, 23, 24, 25, 26], "reason": "logs",
     "ocr": True,
     "detail": "Field logs and geosummary logs had no text in the first reading; these are the pages left "
               "out of it. Record the lithologic intervals."},
    {"source_id": "ngmdb:96652", "pages": [79, 80, 81, 82], "reason": "logs", "ocr": True,
     "detail": "Appendix lithologic logs of piezometers: the text layer holds only the captions."},
    {"source_id": "ngmdb:42961", "pages": [1], "reason": "map_face",
     "detail": "Contour values and power/hand auger-hole and seismic-station elevations on the map face "
               "(OCR garbled in the first reading): record them as surfaces and contours where legible."},
]


class RereadError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_pages(text: str) -> list[int]:
    """'1,3-5' (or '280–282') -> [1, 3, 4, 5]."""
    out: set[int] = set()
    for part in re.split(r"[,\s]+", (text or "").replace("–", "-").replace("—", "-")):
        if not part:
            continue
        a, _, b = part.partition("-")
        out |= set(range(int(a), int(b or a) + 1))
    return sorted(out)


def _catalog() -> dict[str, dict]:
    return {r["id"]: r for r in json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text())}


def _stored_on(extracted: dict, pages: set[int]) -> int:
    from extract.ingest import SECTIONS, _walk_values
    return sum(1 for _, v in _walk_values({k: extracted.get(k, []) for k in SECTIONS}) if v.get("page") in pages)


def _ocr_pages(doc: dict, text_path: Path, chosen: list[int], ocr: Callable[[Path, int], tuple[str, str]],
               cache_dir: Path) -> list[int]:
    """OCR chosen pages not OCRed yet from the cached PDF; adds the OCR text to the page (any text layer kept)."""
    by_page = {p["page"]: p for p in doc["pages"]}
    todo = [n for n in chosen if n in by_page and by_page[n].get("method") != "ocr"]
    done = []
    for n in todo:
        page = by_page[n]
        f = doc["files"][page.get("file", 0)]
        pdf = Path(f.get("path") or "")
        if not f.get("path") or not pdf.exists():
            raise RereadError(f"page {n} needs OCR but the cached PDF ({f.get('path')}) is missing; "
                              "a re-read never downloads")
        layout, raw = ocr(pdf, page.get("file_page", n))
        if not pdftext.has_text(layout):
            continue
        keep = (page.get("text") or "").strip()
        page.update(text=(keep + "\n\n" + layout).strip(), raw=((page.get("raw") or "").strip() + "\n\n" + raw).strip(),
                    method="ocr", needs_ocr=False, reread_ocr=_now())
        done.append(n)
    if done:
        text_path.write_text(json.dumps(doc, ensure_ascii=False))
    return done


def _default_ocr(cache_dir: Path) -> Callable[[Path, int], tuple[str, str]]:
    if not (pdftext.shutil.which("tesseract") and pdftext.shutil.which("pdftoppm")):
        raise RereadError("--ocr needs tesseract and pdftoppm (sudo apt-get install -y tesseract-ocr poppler-utils)")

    def run(pdf: Path, n: int) -> tuple[str, str]:
        work = Path(cache_dir) / "ocr" / "reread"
        work.mkdir(parents=True, exist_ok=True)
        return pdftext.ocr_page(pdf, n, work)
    return run


def build(sid: str, pages: list[int] | None = None, packet_names: list[str] | None = None, reason: str = "re-read",
          queue_ids: list[str] | tuple = (), ocr: Callable | bool = False, cache_dir: Path = CACHE,
          catalog: dict | None = None, extracted_dir: Path = EXTRACTED, scopes: dict | None = None,
          max_tokens: int | None = None, images: bool | dict = False, image_render: Callable | None = None,
          images_optional: bool = False) -> dict:
    """Re-read packets for chosen pages (or the pages of chosen packets) of one document, from the cache only.

    images (True, or {"dpi", "grid", "crop", "overview"}) also renders page tiles from the cached PDF
    (extract/images.py), keeps pages with no text, and lists the tiles in the packet header. With
    images_optional, a failed render is reported in "image_error" and the text packets are built anyway."""
    cache_dir = Path(cache_dir)
    safe = packets.safe_id(sid)
    text_path = cache_dir / "text" / f"{safe}.json"
    if not text_path.exists():
        raise RereadError(f"no cached text for {sid} at {text_path}; a re-read never downloads. Get the text "
                          f"first with python -m harvest.pdfs --id {sid} (the normal download and text step, "
                          "throttled and resumable)")
    doc = json.loads(text_path.read_text())
    catalog = _catalog() if catalog is None else catalog
    rec = catalog.get(sid) or doc.get("record")
    if rec is None:
        raise RereadError(f"{sid} is not in the catalog")
    pdir = cache_dir / "packets" / safe
    chosen = set(pages or [])
    if packet_names:
        index_path = pdir / "index.json"
        if not index_path.exists():
            raise RereadError(f"no packet index for {sid}; give --pages instead")
        by_name = {p["file"].removesuffix(".md"): p for p in json.loads(index_path.read_text())["packets"]}
        missing = [n for n in packet_names if n not in by_name]
        if missing:
            raise RereadError(f"{sid} has no {', '.join(missing)} (packets: {sorted(by_name)})")
        chosen |= {pg for n in packet_names for pg in by_name[n]["pages"]}
    if not chosen:
        raise RereadError("give --pages or --packets")
    have = {p["page"] for p in doc["pages"]}
    unknown = sorted(chosen - have)
    if unknown:
        raise RereadError(f"{sid} has no page {scope.describe(unknown)} (pages 1-{max(have)})")
    rec_scope = scope.for_record(sid, doc, scope.load() if scopes is None else scopes)
    if rec_scope:
        outside = sorted(chosen - set(rec_scope["pages"]))
        if outside:
            raise RereadError(f"pages {scope.describe(outside)} are outside {sid}'s scope "
                              f"({scope.describe(rec_scope['pages'])}, config/catalog_scope.json)")
    ocred = []
    if ocr:
        fn = _default_ocr(cache_dir) if ocr is True else ocr
        ocred = _ocr_pages(doc, text_path, sorted(chosen), fn, cache_dir)
    no_text = sorted(p["page"] for p in doc["pages"] if p["page"] in chosen and not pdftext.has_text(p.get("text", "")))
    img, image_error = _render_images(sid, sorted(chosen), images, image_render, cache_dir, images_optional)
    if not img:
        chosen -= set(no_text)
    if not chosen:
        raise RereadError(f"pages {scope.describe(no_text)} of {sid} have no text; OCR them with --ocr "
                          "(from the cached PDF) or wait for image reading")
    want = sorted(chosen)

    rdir = pdir / packets.REREAD_DIR
    index_path = rdir / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"source_id": sid, "packets": []}
    ingested = _ingested_rereads(Path(extracted_dir) / f"{safe}.json")
    request = {"request_pages": want, "reason": reason, "queue_ids": list(queue_ids)}
    if img:
        request["images"] = img["request"]
    reuse = [p for p in index["packets"] if {k: p.get(k) for k in request} == request
             and p["file"].removesuffix(".md") not in ingested and (rdir / p["file"]).exists() and not ocred]
    if not reuse:
        info = {"pages": want, "reason": reason,
                "scope_note": rec_scope.get("note") if rec_scope else None, "images": img}
        built = packets.build(doc, rec, max_tokens or CONFIG["packet_max_tokens"], CONFIG["chars_per_token"],
                              reread=info)
        n0 = max([int(re.sub(r"\D", "", p["file"]) or 0) for p in index["packets"]] or [0])
        rdir.mkdir(parents=True, exist_ok=True)
        extracted_path = Path(extracted_dir) / f"{safe}.json"
        stored = _stored_on(json.loads(extracted_path.read_text()), chosen) if extracted_path.exists() else 0
        for i, p in enumerate(built, n0 + 1):
            name = f"reread-{i:02d}"
            (rdir / f"{name}.md").write_text(p["text"])
            entry = {"file": f"{name}.md", "pages": p["pages"], "blocks": p["blocks"],
                     "estimated_tokens": p["estimated_tokens"], **request, "stored_before": stored,
                     "built_at": _now()}
            index["packets"].append(entry)
            reuse.append(entry)
        index_path.write_text(json.dumps(index, indent=1))
    out = [{"packet": p["file"].removesuffix(".md"), "path": str(rdir / p["file"]), "pages": p["pages"],
            "blocks": p["blocks"], "estimated_tokens": p["estimated_tokens"],
            "result_path": str(cache_dir / "results" / f"{safe}.{p['file'].removesuffix('.md')}.json")}
           for p in reuse]
    return {"id": sid, "citation": rec.get("citation"), "reason": reason, "pages": want, "no_text": no_text,
            "ocred": ocred, "queue_ids": list(queue_ids), "packets": out,
            "estimated_tokens": sum(p["estimated_tokens"] for p in out) + (img["estimated_tokens"] if img else 0),
            **({"images": img} if img else {}), **({"image_error": image_error} if image_error else {})}


def _render_images(sid: str, pages: list[int], images, image_render, cache_dir: Path,
                   optional: bool) -> tuple[dict | None, str | None]:
    """Tiles of the chosen pages (extract.images.render), or (None, error) when optional and it fails."""
    if not images:
        return None, None
    from extract import images as image_mod
    opts = {k: v for k, v in (images if isinstance(images, dict) else {}).items() if v is not None}
    try:
        m = (image_render or image_mod.render)(sid, pages, cache_dir=cache_dir, **opts)
    except image_mod.ImagesError as err:
        if optional:
            return None, str(err)
        raise RereadError(f"images: {err}") from None
    req = {k: (list(v) if isinstance(v, tuple) else v) for k, v in opts.items()}
    return m | {"request": req}, None


def _ingested_rereads(extracted_path: Path) -> set[str]:
    try:
        d = json.loads(Path(extracted_path).read_text())
    except (OSError, ValueError):
        return set()
    return {n for i in d.get("ingests") or [] if i.get("reread") for n in i["reread"].get("packets", [])}


# --- the re-read queue ---------------------------------------------------------------

_PAGE_REF = re.compile(r"\b(?:pages?|pp?\.)\s*(\d+(?:\s*[-–]\s*\d+)?(?:\s*(?:,|and)\s*\d+(?:\s*[-–]\s*\d+)?)*)", re.I)


def note_pages(line: str) -> list[int]:
    """Page numbers a notes line cites ('p. 1', 'pages 3-4', 'pp. 280-282, 300')."""
    out: set[int] = set()
    for m in _PAGE_REF.finditer(line):
        out |= set(parse_pages(re.sub(r"\band\b", ",", m.group(1))))
    return sorted(out)


def _item_id(sid: str, reason: str, pages: list[int]) -> str:
    return f"{sid}:{reason}:p{scope.describe(pages).replace(' ', '')}"


def _has_subsurface(d: dict, pages: set[int]) -> bool:
    from extract.ingest import _walk_values
    return any(v.get("page") in pages for _, v in _walk_values({k: d.get(k, []) for k in SUBSURFACE_SECTIONS}))


def _status(item: dict, d: dict | None) -> dict:
    """pending, or done (with done_at) once ingests carrying the item's queue id cover all its pages."""
    covered, last = set(), None
    for i in (d or {}).get("ingests") or []:
        rr = i.get("reread") or {}
        if item["id"] in rr.get("queue_ids", []):
            covered |= set(rr.get("pages", []))
            last = i.get("at")
    if set(item["pages"]) <= covered:
        return {"status": "done", "done_at": last}
    return {"status": "pending"}


def build_queue(extracted_dir: Path = EXTRACTED, known: list[dict] | None = None, old: dict | None = None) -> dict:
    """The re-read queue: SUBSURFACE notes lines, known re-reads and earlier manual items, with their status."""
    known = KNOWN if known is None else known
    extracted_dir = Path(extracted_dir)
    docs = {}
    for f in sorted(extracted_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except ValueError:
            continue
        docs[d.get("source_id")] = d
    items: dict[str, dict] = {}
    for sid, d in docs.items():
        for line in dict.fromkeys(ln.strip() for ln in (d.get("notes") or "").splitlines()):
            if not line.startswith("SUBSURFACE:") or re.match(r"SUBSURFACE:\s*none\b", line, re.I):
                continue
            pages = note_pages(line) or sorted(packets.block_page(b) for b in d.get("blocks_done") or [])
            if not pages or _has_subsurface(d, set(pages)):
                continue
            iid = _item_id(sid, "subsurface_fields", pages)
            items.setdefault(iid, {"id": iid, "source_id": sid, "pages": pages, "reason": "subsurface_fields",
                                   "detail": line[:400], "origin": "notes"})
    for k in known:
        iid = _item_id(k["source_id"], k["reason"], k["pages"])
        items[iid] = {"id": iid, "origin": "ROADMAP 1.9", **k}
    old_items = {i["id"]: i for i in (old or {}).get("items", [])}
    for iid, i in old_items.items():
        if i.get("origin") == "manual":
            items.setdefault(iid, dict(i))
    out = []
    for iid, item in items.items():
        item = {k: v for k, v in item.items() if k not in ("status", "done_at")}
        item.setdefault("ocr", False)
        item.setdefault("images", wants_images(item))
        item["added_at"] = old_items.get(iid, {}).get("added_at") or _now()
        out.append(item | _status(item, docs.get(item["source_id"])))
    order = {"ROADMAP 1.9": 0, "manual": 1, "notes": 2}
    out.sort(key=lambda i: (i["status"] != "pending", order.get(i["origin"], 3), i["source_id"], i["pages"]))
    tally: dict[str, int] = {}
    for i in out:
        tally[i["reason"]] = tally.get(i["reason"], 0) + 1
    return {"about": "Documents already read whose chosen pages need a re-read (python -m extract.reread; "
                     "see extract/SESSION.md).",
            "count": len(out), "pending": sum(i["status"] == "pending" for i in out), "by_reason": tally,
            "items": out}


def load_queue(path: Path = QUEUE_PATH) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def write_queue(q: dict, path: Path = QUEUE_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(q, indent=1, ensure_ascii=False) + "\n")


def add_item(q: dict | None, sid: str, pages: list[int], reason: str, detail: str, ocr: bool = False) -> dict:
    q = q or {"items": []}
    code = re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_")[:40] or "manual"
    iid = _item_id(sid, code, pages)
    q["items"] = [i for i in q.get("items", []) if i["id"] != iid] + [
        {"id": iid, "source_id": sid, "pages": pages, "reason": code, "detail": detail, "origin": "manual",
         "ocr": ocr, "status": "pending", "added_at": _now()}]
    return q


def next_rereads(queue: dict, n: int = 3, max_tokens: int | None = None, ids: list[str] | None = None,
                 log: Callable[[str], None] = print, **kw) -> list[dict]:
    """Packets for the next pending queue items, in queue order, until n items or max_tokens."""
    out, tokens = [], 0
    for item in queue.get("items", []):
        if len(out) >= n or (max_tokens and out and tokens >= max_tokens):
            break
        if item.get("status") != "pending" or (ids and item["source_id"] not in ids):
            continue
        try:
            b = build(item["source_id"], pages=item["pages"], reason=item.get("detail") or item["reason"],
                      queue_ids=[item["id"]], ocr=bool(item.get("ocr")), images=wants_images(item),
                      images_optional=True, **kw)
        except RereadError as err:
            log(f"skip {item['source_id']} pages {scope.describe(item['pages'])}: {err}")
            continue
        if b.get("image_error"):
            log(f"no images for {item['source_id']} pages {scope.describe(item['pages'])}: {b['image_error']}")
        if max_tokens and out and tokens + b["estimated_tokens"] > max_tokens:
            break
        tokens += b["estimated_tokens"]
        out.append(b | {"queue_id": item["id"], "queue_reason": item["reason"]})
    return out


def _print(batch: list[dict]) -> None:
    for i, b in enumerate(batch, 1):
        print(f"\n[{i}] {b['id']} re-read pages {scope.describe(b['pages'])} "
              f"({len(b['packets'])} packets, ~{b['estimated_tokens']:,} tokens)")
        print(f"    {b['citation'] or ''}")
        print(f"    reason: {b['reason']}")
        if b.get("queue_id"):
            print(f"    queue: {b['queue_id']}")
        if b["ocred"]:
            print(f"    OCRed now: pages {scope.describe(b['ocred'])}")
        if b["no_text"]:
            print(f"    left out (no text): pages {scope.describe(b['no_text'])}")
        for p in b["packets"]:
            print(f"    read:  {p['path']}  (pages {scope.describe(p['pages'])}, ~{p['estimated_tokens']:,} tokens)")
            print(f"    write: {p['result_path']}")
        if b.get("images"):
            im = b["images"]
            print(f"    images: {im['manifest']}  ({len(im['tiles'])} tiles, ~{im['estimated_tokens']:,} tokens)")
            for t in im["tiles"]:
                print(f"    view:  {Path(im['dir']) / t['file']}  ({t['tile']}, page {t['page']})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("id", nargs="?", help="catalog id of the document to re-read")
    ap.add_argument("--pages", help="pages to re-read, e.g. 1,3-5")
    ap.add_argument("--packets", help="packets whose pages to re-read, e.g. packet-02,packet-03")
    ap.add_argument("--reason", help="why (goes into the packet and the history of replaced values)")
    ap.add_argument("--ocr", action="store_true", help="OCR the chosen pages from the cached PDF first")
    ap.add_argument("--images", action="store_true", help="also render page tiles from the cached PDF "
                    "(extract/images.py); --next does this for map-face, image-page, subsurface and section items")
    ap.add_argument("--dpi", type=float, help="with --images: render resolution")
    ap.add_argument("--grid", help="with --images: COLSxROWS tiles, e.g. 3x3")
    ap.add_argument("--next", action="store_true", help="hand out the next pending items of the re-read queue")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--max-tokens", type=int)
    ap.add_argument("--queue", action="store_true", help="rebuild data/review/reread_queue.json")
    ap.add_argument("--add", action="store_true", help="add the id, --pages and --reason to the re-read queue")
    ap.add_argument("--detail", help="with --add: what to read on those pages (default: the reason)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.queue or args.add:
            q = load_queue()
            if args.add:
                if not (args.id and args.pages and args.reason):
                    ap.error("--add needs an id, --pages and --reason")
                q = add_item(q, args.id, parse_pages(args.pages), args.reason, args.detail or args.reason, args.ocr)
            q = build_queue(old=q)
            write_queue(q)
            print(json.dumps({k: q[k] for k in ("count", "pending", "by_reason")}, indent=1))
            return 0
        if args.next:
            q = build_queue(old=load_queue())
            batch = next_rereads(q, n=args.n, max_tokens=args.max_tokens, ids=[args.id] if args.id else None,
                                 log=lambda m: print(m, file=sys.stderr))
        else:
            if not args.id:
                ap.error("give a document id, --next or --queue")
            pages = parse_pages(args.pages) if args.pages else None
            names = [s.strip() for s in args.packets.split(",")] if args.packets else None
            q = build_queue(old=load_queue())
            want = set(pages or [])
            qids = [i["id"] for i in q["items"] if i["source_id"] == args.id and i["status"] == "pending"
                    and want and set(i["pages"]) <= want]
            reason = args.reason or "; ".join(i["detail"] for i in q["items"] if i["id"] in qids) or "re-read"
            imgs = False
            if args.images or args.dpi or args.grid:
                from extract.images import ImagesError, parse_grid
                try:
                    imgs = {"dpi": args.dpi, "grid": parse_grid(args.grid) if args.grid else None}
                except ImagesError as err:
                    raise RereadError(str(err)) from None
            batch = [build(args.id, pages=pages, packet_names=names, reason=reason, queue_ids=qids, ocr=args.ocr,
                           images=imgs)]
    except RereadError as err:
        print(f"re-read refused: {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(batch, indent=1, ensure_ascii=False))
    else:
        _print(batch)
        if not batch:
            print("No pending re-reads with cached text.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
