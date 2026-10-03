"""Harvest the USGS Geolex lexicon of geologic unit names used in South Carolina.

For each unit: current and former usage, whether the name is abandoned and
what replaced it, geologic age, subunits, type locality and the literature
it cites. Used to recognize the same unit across maps (model.units.Lexicon).
Unit pages are cached under the checkpoint directory, so reruns resume.

    python -m harvest.geolex [--out data/lexicon] [--checkpoints .checkpoints/geolex]
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from harvest.catalog import _get
from model.provenance import ExtractionMethod, StoredValue
from model.units import AGE_SOURCE, age_range

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://ngmdb.usgs.gov"


def _text(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<[^>]+>", "", t)
    return "\n".join(line.strip() for line in htmllib.unescape(t).splitlines() if line.strip())


def parse_listing(page: str) -> list[dict]:
    rows = []
    for block in re.findall(r'<ul class="glx_hit">(.*?)</ul>', page, re.S):
        m = re.search(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', block)
        if not m:
            continue
        items = re.findall(r'<li style="margin-left:10px;">(.*?)</li>', block, re.S)
        lines = [line for item in items for line in _text(item).splitlines()]
        notes = [line.strip("()") for line in lines if line.startswith("(")]
        usage = [line for line in lines if not line.startswith("(") and line != "No current usage."]
        note = " ".join(notes)
        abandoned = "No current usage." in lines or re.search(r"abandoned|obsolete|same as", note, re.I)
        replaced = re.search(r"See ([A-Z][\w' .-]*?)\.", note)
        rows.append({
            "name": htmllib.unescape(m.group(2)).strip(),
            "url": BASE + m.group(1) if m.group(1).startswith("/") else m.group(1),
            "usage": usage,
            "notes": notes,
            "status": "abandoned" if abandoned else "current",
            "replaced_by": replaced.group(1).strip() if replaced and abandoned else None,
        })
    return rows


def _section(page: str, heading: str) -> str | None:
    m = re.search(r'<span class="strongheading">' + re.escape(heading) + r'</span>\s*<p>(.*?)</p>', page, re.S)
    return _text(m.group(1)) if m else None


def parse_unit(page: str) -> dict:
    usage = _section(page, "Usage:")
    locality = _section(page, "Type section, locality, area and/or origin of name:")
    refs = []
    for group in re.findall(r"\(([^()]*\d{4}[^()]*)\)", locality or ""):
        for part in group.split(";"):
            m = re.search(r"((?:[A-Z]\.\s*)*[A-Z][\w'-]+(?: and others| and [A-Z][\w'-]+)?),? (\d{4})", part)
            if m and not re.match(r"USGS|US ", m.group(1)):
                ref = f"{m.group(1)}, {m.group(2)}"
                if ref not in refs:
                    refs.append(ref)
    return {
        "usage": usage.splitlines() if usage else [],
        "subunits": _section(page, "Subunits:"),
        "age": _section(page, "Geologic age:"),
        "type_locality": locality,
        "province": _section(page, "AAPG geologic province:"),
        "references": refs,
    }


def to_record(row: dict, unit: dict, retrieved_at: str) -> dict:
    locator = row["url"].rsplit("/", 1)[-1].removesuffix(".html")
    v = StoredValue(value=None, source_id="usgs-geolex", page=None, locator=locator,
                    extraction_method=ExtractionMethod.CATALOG_IMPORT, confidence=1.0)
    rng = age_range(unit.get("age"))
    return {
        "name": row["name"],
        "status": row["status"],
        "replaced_by": row["replaced_by"],
        "usage": unit.get("usage") or row["usage"],
        "notes": row["notes"],
        "age": unit.get("age"),
        "age_range_ma": list(rng) if rng else None,
        # Converted from the age text with the ICS chart, not stated by Geolex.
        "age_range_inferred": True,
        "age_range_source": AGE_SOURCE,
        "subunits": unit.get("subunits"),
        "type_locality": unit.get("type_locality"),
        "province": unit.get("province"),
        "references": unit.get("references", []),
        "url": row["url"],
        "source_id": v.source_id,
        "locator": v.locator,
        "extraction_method": v.extraction_method.value,
        "confidence": v.confidence,
        "retrieved_at": retrieved_at,
    }


def run(out_dir: Path, checkpoint_dir: Path, state: str = "SC", log: Callable[..., None] = print) -> list[dict]:
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    first = _get(f"{BASE}/lex-bin/results.pl", {"State": state}, raw=True)
    sid = re.search(r"createHitListContent\((\d+)", first).group(1)
    rows, pos = [], 0
    while True:
        page = _get(f"{BASE}/lex-bin/display_glx_content.pl", {"units_pg": 100, "srhid": sid, "pos": pos, "u": 1},
                    raw=True)
        batch = parse_listing(page)
        rows += batch
        total = int(re.search(r"of (\d+)\)", page).group(1))
        if not batch or len(rows) >= total:
            break
        pos += len(batch)
    log(f"Geolex: {len(rows)} units for {state}")
    ckpt = Path(checkpoint_dir)
    ckpt.mkdir(parents=True, exist_ok=True)
    records = []
    for row in rows:
        f = ckpt / (row["url"].rsplit("/", 1)[-1] + ".json")
        if f.exists():
            unit = json.loads(f.read_text())
        else:
            unit = parse_unit(_get(row["url"], raw=True))
            f.write_text(json.dumps(unit))
        records.append(to_record(row, unit, retrieved_at))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"geolex_{state.lower()}.json").write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n")
    log(f"wrote {len(records)} units; {sum(r['status'] == 'current' for r in records)} current")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "lexicon")
    parser.add_argument("--checkpoints", type=Path, default=ROOT / ".checkpoints" / "geolex")
    args = parser.parse_args()
    run(args.out, args.checkpoints)


if __name__ == "__main__":
    main()
