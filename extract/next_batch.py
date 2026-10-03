"""Hand out the next packets for a reading session, building them if missing.

    python -m extract.next_batch --n 5 [--max-tokens 250000] [--id ngmdb:10009] [--json]

Documents a session has started (data/extracted/<id>.json with
"complete": false) come first, with only their unread packets; then pending
documents in harvest-queue order (Charleston County first; see
harvest/pdfs.py), skipping finished documents and ones listed in
data/review/needs_access.json. Packets are handed out one by one until
--max-tokens is reached, so a long document can be read over several
sessions; the first packet is always handed out even if it alone exceeds
the budget.

For each document it makes sure the page text exists (downloading and
OCRing when the cache is empty, as in a fresh Claude Code session) and that
packets exist in .cache/packets/<id>/. Prints, per packet, the file to read
and the result path to write (.cache/results/<id>.<packet>.json).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Callable

from extract import packets, pdftext
from harvest import pdfs

ROOT = Path(__file__).resolve().parent.parent
CONFIG = pdfs.CONFIG


def _needs_access_ids(review_dir: Path) -> set[str]:
    try:
        return {r["id"] for r in json.loads((Path(review_dir) / "needs_access.json").read_text())["records"]}
    except (OSError, ValueError, KeyError):
        return set()


def ensure_packets(rec: dict, cache_dir: Path, max_tokens: int | None = None) -> dict | None:
    sid = packets.safe_id(rec["id"])
    text_path = Path(cache_dir) / "text" / f"{sid}.json"
    pdir = Path(cache_dir) / "packets" / sid
    index = pdir / "index.json"
    if not text_path.exists():
        return None
    stale = (not index.exists() or index.stat().st_mtime < text_path.stat().st_mtime
             or "blocks" not in json.loads(index.read_text()))
    if stale:
        doc = json.loads(text_path.read_text())
        built = packets.build(doc, rec, max_tokens or CONFIG["packet_max_tokens"], CONFIG["chars_per_token"])
        if not built:
            return None
        packets.write(built, rec, Path(cache_dir) / "packets")
    return json.loads(index.read_text())


def progress(extracted_dir: Path, sid: str) -> dict | None:
    """The extracted file's progress: None if not started; legacy files (no 'complete') count as complete."""
    path = Path(extracted_dir) / f"{sid}.json"
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
    except ValueError:
        return None
    return {"complete": d.get("complete", True), "blocks_done": set(d.get("blocks_done") or [])}


def next_batch(n: int = 5, ids: list[str] | None = None, catalog: list[dict] | None = None, pilot_bbox=None,
               cache_dir: Path = ROOT / ".cache", checkpoint_dir: Path = ROOT / ".checkpoints" / "pdfs",
               extracted_dir: Path = ROOT / "data" / "extracted", review_dir: Path = ROOT / "data" / "review",
               max_tokens: int | None = None, max_minutes: float | None = None, fetcher=None, ocr="auto",
               allow_partial: bool = False, packet_max_tokens: int | None = None,
               log: Callable[..., None] = print) -> list[dict]:
    if catalog is None:
        catalog = json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text())
    cache_dir, checkpoint_dir = Path(cache_dir), Path(checkpoint_dir)
    order = pdfs.queue(catalog, pilot_bbox)
    if ids:
        order = [r for r in order if r["id"] in ids]
    started = {r["id"] for r in order if (p := progress(extracted_dir, packets.safe_id(r["id"]))) and not p["complete"]}
    order = [r for r in order if r["id"] in started] + [r for r in order if r["id"] not in started]
    blocked = set() if ids else _needs_access_ids(review_dir)
    email = os.environ.get("CONTACT_EMAIL", "").strip() or None
    fetcher = fetcher or pdfs.HttpFetcher()
    deadline = None if max_minutes is None else time.monotonic() + max_minutes * 60
    out, tokens = [], 0
    for rec in order:
        if len(out) >= n or (deadline and time.monotonic() > deadline):
            break
        if max_tokens and out and tokens >= max_tokens:
            break
        sid = packets.safe_id(rec["id"])
        prog = progress(extracted_dir, sid)
        if (prog and prog["complete"]) or rec["id"] in blocked:
            continue
        ck = pdfs._load(checkpoint_dir / f"{sid}.json") or {}
        if ck.get("status") == "needs_ocr" and not allow_partial:
            if ocr is None or pdftext.ocr_engine() is None:
                log(f"skip {rec['id']}: needs OCR ({ck.get('reason')})")
                continue
            (cache_dir / "text" / f"{sid}.json").unlink(missing_ok=True)  # read again with OCR
        index = ensure_packets(rec, cache_dir, packet_max_tokens)
        if index is None:
            ck = pdfs.process(rec, fetcher, checkpoint_dir, cache_dir, email, ocr=ocr,
                              log=lambda m: log(pdfs.redact(str(m), email or "")))
            if ck.get("status") != "text" and not (allow_partial and ck.get("status") == "needs_ocr"):
                log(f"skip {rec['id']}: {ck.get('status')} ({ck.get('reason') or 'no text'})")
                continue
            index = ensure_packets(rec, cache_dir, packet_max_tokens)
            if index is None:
                log(f"skip {rec['id']}: no readable pages")
                continue
        done = prog["blocks_done"] if prog else set()
        todo = [p for p in index["packets"] if not set(p["blocks"]) <= done]
        if not todo:
            continue
        chosen = []
        for p in todo:
            if max_tokens and (out or chosen) and tokens + p["estimated_tokens"] > max_tokens:
                break
            chosen.append(p)
            tokens += p["estimated_tokens"]
        if not chosen:
            break
        pdir = cache_dir / "packets" / sid
        name = lambda p: p["file"].removesuffix(".md")
        out.append({"id": rec["id"], "title": rec.get("title"), "citation": rec.get("citation"),
                    "tier": rec.get("_tier"), "started": rec["id"] in started,
                    "packets_total": len(index["packets"]), "remaining_after": len(todo) - len(chosen),
                    "estimated_tokens": sum(p["estimated_tokens"] for p in chosen),
                    "packets": [{"packet": name(p), "path": str(pdir / p["file"]), "pages": p["pages"],
                                 "blocks": p["blocks"], "estimated_tokens": p["estimated_tokens"],
                                 "result_path": str(cache_dir / "results" / f"{sid}.{name(p)}.json")}
                                for p in chosen],
                    "skipped_pages": index.get("skipped", {})})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=5, help="at most N documents")
    ap.add_argument("--id", action="append", dest="ids")
    ap.add_argument("--max-tokens", type=int, help="stop handing out packets past this many packet tokens")
    ap.add_argument("--max-minutes", type=float, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-partial", action="store_true",
                    help="also serve documents whose scanned files still need OCR (their text parts only)")
    args = ap.parse_args()
    batch = next_batch(n=args.n, ids=args.ids, max_tokens=args.max_tokens, max_minutes=args.max_minutes,
                       allow_partial=args.allow_partial)
    if args.json:
        print(json.dumps(batch, indent=1, ensure_ascii=False))
        return
    for i, b in enumerate(batch, 1):
        state = "continue" if b["started"] else "new"
        print(f"\n[{i}] {b['id']} ({state}, tier {b['tier']}, {len(b['packets'])} of {b['packets_total']} packets, "
              f"~{b['estimated_tokens']:,} tokens; {b['remaining_after']} left after this)")
        print(f"    {b['citation'] or b['title']}")
        for p in b["packets"]:
            print(f"    read:  {p['path']}  (pages {p['pages'][0]}-{p['pages'][-1]}, ~{p['estimated_tokens']:,} tokens)")
            print(f"    write: {p['result_path']}")
    if not batch:
        print("No pending documents with full text.")


if __name__ == "__main__":
    main()
