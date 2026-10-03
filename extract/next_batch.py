"""Print the next documents for a reading session, building their packets if missing.

    python -m extract.next_batch --n 5 [--id ngmdb:10009] [--max-tokens 300000] [--json]

Walks the harvest queue (Charleston County first; see harvest/pdfs.py),
skipping documents already in data/extracted/ and ones listed in
data/review/needs_access.json. For each pending document it makes sure the
page text exists (downloading the PDF and running pdftotext/OCR when the
cache is empty, as in a fresh Claude Code session) and that packets exist in
.cache/packets/<id>/. Prints, per document, the packet files to read and
the path to write the result JSON to (.cache/results/<id>.json).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Callable

from extract import packets
from harvest import pdfs

ROOT = Path(__file__).resolve().parent.parent
CONFIG = pdfs.CONFIG


def _needs_access_ids(review_dir: Path) -> set[str]:
    try:
        return {r["id"] for r in json.loads((Path(review_dir) / "needs_access.json").read_text())["records"]}
    except (OSError, ValueError, KeyError):
        return set()


def ensure_packets(rec: dict, cache_dir: Path) -> dict | None:
    sid = packets.safe_id(rec["id"])
    text_path = Path(cache_dir) / "text" / f"{sid}.json"
    pdir = Path(cache_dir) / "packets" / sid
    index = pdir / "index.json"
    if not text_path.exists():
        return None
    if not index.exists() or index.stat().st_mtime < text_path.stat().st_mtime:
        doc = json.loads(text_path.read_text())
        built = packets.build(doc, rec, CONFIG["packet_max_tokens"], CONFIG["chars_per_token"])
        if not built:
            return None
        packets.write(built, rec, Path(cache_dir) / "packets")
    return json.loads(index.read_text())


def next_batch(n: int = 5, ids: list[str] | None = None, catalog: list[dict] | None = None, pilot_bbox=None,
               cache_dir: Path = ROOT / ".cache", checkpoint_dir: Path = ROOT / ".checkpoints" / "pdfs",
               extracted_dir: Path = ROOT / "data" / "extracted", review_dir: Path = ROOT / "data" / "review",
               max_tokens: int | None = None, max_minutes: float | None = None, fetcher=None, ocr="auto",
               log: Callable[..., None] = print) -> list[dict]:
    if catalog is None:
        catalog = json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text())
    cache_dir, checkpoint_dir = Path(cache_dir), Path(checkpoint_dir)
    order = pdfs.queue(catalog, pilot_bbox)
    if ids:
        order = [r for r in order if r["id"] in ids]
    blocked = set() if ids else _needs_access_ids(review_dir)
    email = os.environ.get("CONTACT_EMAIL", "").strip() or None
    fetcher = fetcher or pdfs.HttpFetcher()
    deadline = None if max_minutes is None else time.monotonic() + max_minutes * 60
    out, tokens = [], 0
    for rec in order:
        if len(out) >= n or (deadline and time.monotonic() > deadline):
            break
        sid = packets.safe_id(rec["id"])
        if (Path(extracted_dir) / f"{sid}.json").exists() or rec["id"] in blocked:
            continue
        index = ensure_packets(rec, cache_dir)
        if index is None:
            ck = pdfs.process(rec, fetcher, checkpoint_dir, cache_dir, email, ocr=ocr,
                              log=lambda m: log(pdfs.redact(str(m), email or "")))
            if ck.get("status") != "text":
                log(f"skip {rec['id']}: {ck.get('status')} ({ck.get('reason') or 'no text'})")
                continue
            index = ensure_packets(rec, cache_dir)
            if index is None:
                log(f"skip {rec['id']}: no readable pages")
                continue
        if max_tokens and out and tokens + index["estimated_tokens"] > max_tokens:
            break
        tokens += index["estimated_tokens"]
        pdir = cache_dir / "packets" / sid
        out.append({"id": rec["id"], "title": rec.get("title"), "citation": rec.get("citation"),
                    "tier": rec.get("_tier"), "estimated_tokens": index["estimated_tokens"],
                    "packets": [{"path": str(pdir / p["file"]), "pages": p["pages"],
                                 "estimated_tokens": p["estimated_tokens"]} for p in index["packets"]],
                    "skipped_pages": index.get("skipped", {}),
                    "result_path": str(cache_dir / "results" / f"{sid}.json")})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--id", action="append", dest="ids")
    ap.add_argument("--max-tokens", type=int, help="stop adding documents past this many packet tokens")
    ap.add_argument("--max-minutes", type=float, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    batch = next_batch(n=args.n, ids=args.ids, max_tokens=args.max_tokens, max_minutes=args.max_minutes)
    if args.json:
        print(json.dumps(batch, indent=1, ensure_ascii=False))
        return
    for i, b in enumerate(batch, 1):
        print(f"\n[{i}] {b['id']} (tier {b['tier']}, ~{b['estimated_tokens']:,} tokens)")
        print(f"    {b['citation'] or b['title']}")
        for p in b["packets"]:
            print(f"    read:  {p['path']}  (pages {p['pages'][0]}-{p['pages'][-1]}, ~{p['estimated_tokens']:,} tokens)")
        print(f"    write: {b['result_path']}")
    if not batch:
        print("No pending documents with full text.")


if __name__ == "__main__":
    main()
