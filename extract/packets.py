"""Packets: the page text a reading model reads for one document.

One document becomes one or more packets (Markdown text files), each under
`packet_max_tokens` (estimated at `chars_per_token` characters per token).
A packet starts with the catalog record (id, citation, year, scale,
publisher) and then the kept pages, each headed `=== PAGE n (method) ===`
where n is the page number the result JSON must cite. Pages triage marks as
blank, table of contents, index or needing OCR are left out. A page too long
for one packet is split into parts that keep its page number.

Packets live ONLY in the gitignored .cache/packets (CLAUDE.md rule 3).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from extract import triage

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "packets"


def safe_id(source_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", source_id)


def compact(text: str) -> str:
    """Shrink -layout padding: long space runs to three spaces, no trailing spaces, at most one blank line."""
    text = re.sub(r" {4,}", "   ", text or "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def header(record: dict, doc: dict, part: int | None = None, of: int | None = None) -> str:
    scale = record.get("scale")
    lines = [
        f"# Packet {part} of {of} for {record['id']}" if part else f"# Packet for {record['id']}",
        "",
        f"- Catalog id (use as source_id): {record['id']}",
        f"- Title: {record.get('title') or 'not stated'}",
        f"- Citation: {record.get('citation') or record.get('title') or 'not stated'}",
        f"- Year: {record.get('year') or 'not stated'}",
        f"- Scale: {f'1:{scale:,}' if scale else 'not stated'}",
        f"- Publisher: {record.get('publisher') or 'not stated'}",
        f"- Kind: {record.get('kind') or 'not stated'}",
        f"- Files: " + "; ".join(f"{f.get('url')} (pages {f['first_page']}-{f['first_page'] + f['pages'] - 1})"
                                 for f in doc.get("files", [])),
        "",
        "Cite pages by the number in each `=== PAGE n ===` line. Quote text exactly as it appears on that page.",
        "",
    ]
    return "\n".join(lines)


def _blocks(doc: dict, budget: int) -> tuple[list[tuple[int, str]], dict]:
    n_pages = len(doc["pages"])
    blocks: list[tuple[int, str]] = []
    skipped: dict[str, list[int]] = defaultdict(list)
    for p in doc["pages"]:
        t = triage.classify(p.get("text", ""), p["page"], n_pages, method=p.get("method", "pdf_text"))
        if not t["keep"]:
            skipped[t["kind"]].append(p["page"])
            continue
        text = compact(p["text"])
        method = p.get("method", "pdf_text")
        head = f"\n=== PAGE {p['page']} ({method}) ===\n"
        if len(head) + len(text) + 1 <= budget:
            blocks.append((p["page"], head + text + "\n"))
            continue
        room = budget - len(head) - 40
        pieces, rest = [], text
        while rest:
            cut = rest.rfind("\n", 0, room)
            cut = cut if cut > room // 2 else room
            pieces.append(rest[:cut])
            rest = rest[cut:].lstrip("\n")
        for i, piece in enumerate(pieces, 1):
            blocks.append((p["page"], f"\n=== PAGE {p['page']} ({method}, part {i} of {len(pieces)}) ===\n{piece}\n"))
    return blocks, dict(skipped)


def build(doc: dict, record: dict, max_tokens: int = 40000, chars_per_token: int = 4) -> list[dict]:
    limit = max_tokens * chars_per_token
    head_room = len(header(record, doc, 99, 99)) + 10
    blocks, skipped = _blocks(doc, limit - head_room)
    groups: list[list[tuple[int, str]]] = [[]]
    size = 0
    for page, text in blocks:
        if groups[-1] and size + len(text) > limit - head_room:
            groups.append([])
            size = 0
        groups[-1].append((page, text))
        size += len(text)
    if not groups[-1]:
        groups.pop()
    out = []
    for i, g in enumerate(groups, 1):
        text = header(record, doc, i, len(groups)) + "".join(t for _, t in g)
        out.append({"source_id": record["id"], "packet": f"packet-{i:02d}", "of": len(groups),
                    "pages": sorted({p for p, _ in g}), "skipped": skipped, "text": text,
                    "estimated_tokens": len(text) // chars_per_token})
    return out


def write(packets: list[dict], record: dict, cache: Path = CACHE) -> list[Path]:
    d = Path(cache) / safe_id(record["id"])
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("packet-*.md"):
        old.unlink()
    paths = []
    for p in packets:
        path = d / f"{p['packet']}.md"
        path.write_text(p["text"])
        paths.append(path)
    index = {"source_id": record["id"], "citation": record.get("citation"), "title": record.get("title"),
             "packets": [{"file": f"{p['packet']}.md", "pages": p["pages"], "estimated_tokens": p["estimated_tokens"]}
                         for p in packets],
             "skipped": packets[0]["skipped"] if packets else {},
             "estimated_tokens": sum(p["estimated_tokens"] for p in packets)}
    (d / "index.json").write_text(json.dumps(index, indent=1))
    return paths
