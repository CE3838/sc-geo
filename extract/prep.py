"""Get documents ready for reading ahead of time: download, OCR and build packets, no reading.

    python -m extract.prep --todo [--n 20]       # reading-list documents not yet read
    python -m extract.prep ngmdb:10009 ...       # prepare these, one at a time
    python -m extract.prep --next 10             # prepare the next 10 from --todo

Scanned documents can take many minutes of OCR each. Running this as a plain
background job (no reading session) means a session later finds their
packets ready in .cache/ and spends its time reading. Documents are done one
at a time, and OCR is cached per page, so the job can be stopped and run
again without repeating work or downloads. Prints `READY <id> <packets>` or
`NOT-READY <id>` per document.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from extract import next_batch, packets

ROOT = next_batch.ROOT
READING_LIST = ROOT / "config" / "reading_list.json"


def todo(reading_list: Path = READING_LIST, extracted_dir: Path = ROOT / "data" / "extracted",
         review_dir: Path = ROOT / "data" / "review") -> list[str]:
    """Reading-list ids not finished and not waiting for access, in list order."""
    blocked = next_batch._needs_access_ids(review_dir)
    out = []
    for rid in json.loads(Path(reading_list).read_text())["ids"]:
        prog = next_batch.progress(extracted_dir, packets.safe_id(rid))
        if rid in blocked or (prog and prog["complete"]):
            continue
        out.append(rid)
    return out


def prepare(ids: list[str], log: Callable[[str], None] = print, **kw) -> dict[str, str]:
    """Build text and packets for each id in turn; returns READY or NOT-READY per id."""
    status = {}
    for rid in ids:
        try:
            out = next_batch.next_batch(n=1, ids=[rid], max_tokens=1, log=lambda *a: log(" ".join(map(str, a))), **kw)
        except Exception as e:  # keep going: one bad document must not stop the job
            log(f"ERROR {rid} {type(e).__name__} {str(e)[:200]}")
            status[rid] = "NOT-READY"
            continue
        status[rid] = "READY" if out else "NOT-READY"
        log(f"{status[rid]} {rid} {out[0]['packets_total'] if out else ''}".rstrip())
    return status


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--todo", action="store_true", help="list reading-list documents not yet read")
    ap.add_argument("--next", type=int, help="prepare the next N documents from --todo")
    ap.add_argument("--n", type=int, help="with --todo, show at most N")
    args = ap.parse_args()
    if args.todo:
        ids = todo()
        print("\n".join(ids[:args.n] if args.n else ids))
        return
    ids = args.ids or (todo()[:args.next] if args.next else [])
    if not ids:
        ap.error("give ids, --next N or --todo")
    prepare(ids, log=lambda m: print(m, flush=True))


if __name__ == "__main__":
    main()
