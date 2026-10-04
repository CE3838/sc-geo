"""Page scope of catalog records that are one chapter or note of a multi-paper volume.

Some catalog records are one paper of a USGS volume whose only PDF is the
whole volume. config/catalog_scope.json lists, per catalog id, the PDF pages
that belong to the record:

    {"ngmdb:74347": {"url": "https://pubs.usgs.gov/pp/1367/report.pdf",
                     "pdf_pages": [163, 237], "extra_pages": [], "note": "Chapter D ..."}}

`pdf_pages` is an inclusive range of pages of the file at `url`;
`extra_pages` adds single pages (for example the record's cited references
printed after the next paper starts). The scope applies only when the
record's text came from that file, so a record later resolved to its own
chapter PDF is read whole. Packets hold only the scoped pages, progress
counts only them, and ingest refuses values citing any other page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "catalog_scope.json"


def load(path: Path = CONFIG_PATH) -> dict[str, dict]:
    """{catalog id: scope entry}; keys starting with '_' are comments."""
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _bare(url: str | None) -> str:
    return re.sub(r"^[a-z]+://", "", (url or "").strip().lower()).rstrip("/")


def pages(entry: dict, doc: dict) -> set[int] | None:
    """Document page numbers in the entry's scope, or None when the document is not the scoped file."""
    offset = 0
    if entry.get("url"):
        match = [f for f in doc.get("files", []) if _bare(f.get("url")) == _bare(entry["url"])]
        if not match:
            return None
        offset = match[0]["first_page"] - 1
    first, last = entry["pdf_pages"]
    wanted = set(range(first, last + 1)) | set(entry.get("extra_pages") or [])
    return {p + offset for p in wanted}


def for_record(record_id: str, doc: dict, scopes: dict[str, dict] | None = None) -> dict | None:
    """The record's scope as stored in a packet index ({"pages": [...], **entry}), or None."""
    scopes = load() if scopes is None else scopes
    entry = scopes.get(record_id)
    if not entry:
        return None
    allowed = pages(entry, doc)
    if allowed is None:
        return None
    return {"pages": sorted(allowed), **entry}


def describe(page_list: list[int]) -> str:
    """'3-5, 7' for [3, 4, 5, 7]."""
    runs: list[list[int]] = []
    for p in sorted(page_list):
        if runs and p == runs[-1][1] + 1:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in runs)
