"""Recompute the derived fields of committed extractions after a normalizer changes.

    python -m extract.renormalize                      # dry run over data/extracted: report what would change
    python -m extract.renormalize data/extracted/x.json --write

Only `normalized`, `derived_coordinates` and `navd88` (extract/elevations.py,
with the configured datum grid when it has been downloaded) are recomputed, from each stored
value's own `value` and `units`, with the same functions ingest uses
(`ingest.normalized`, `ingest.derived_coordinates`). The value as read, its
quote, page, provenance, confidence, verification and the file's timestamps
are never touched, and nothing is re-read. A dry run (the default) prints a
JSON report and writes nothing.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from extract import elevations, ingest
from model.units import Lexicon

DERIVED = ("normalized", "derived_coordinates", "navd88")


def dumps(doc: dict) -> str:
    """The extracted-file format ingest writes."""
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def _walk(node, path: str):
    """(path, stored value) for every stored value, with paths like groundwater[5].head."""
    if ingest._is_stored(node):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def renormalize_doc(doc: dict, lexicon: Lexicon | None, cfg: dict = ingest.CONFIG,
                    grid=None) -> tuple[dict, list[dict]]:
    """(a recomputed copy of doc, [{path, key, value, old, new}]); doc itself is not modified.

    grid: the NGVD29-to-NAVD88 grid (model.vdatum.ShiftGrid) or None for none."""
    out = copy.deepcopy(doc)
    for key in ingest.SECTIONS:
        for path, entry in _walk(out.get(key, []), key):
            val = {"value": entry.get("value"), **({"units": entry["units"]} if "units" in entry else {})}
            norm = ingest.normalized(path, val, lexicon)
            fresh = {"normalized": norm if norm not in (None, [], {}) else None}
            base = {k: v for k, v in entry.items() if k not in DERIVED}
            fresh["derived_coordinates"] = ingest.derived_coordinates(path, val, base, cfg)
            for k in ("normalized", "derived_coordinates"):
                if fresh[k] is None:
                    entry.pop(k, None)
                else:
                    entry[k] = fresh[k]
    sections = {k: out[k] for k in ingest.SECTIONS if k in out}
    elevations.attach_navd88(sections, doc.get("year"), grid, cfg["vertical_datum"],
                             cfg["confidence"]["inferred_factor"])
    before = dict(_walk({k: doc.get(k, []) for k in ingest.SECTIONS}, ""))
    changes = []
    for path, entry in _walk({k: out.get(k, []) for k in ingest.SECTIONS}, ""):
        old = before.get(path, {})
        for k in DERIVED:
            if old.get(k) != entry.get(k):
                changes.append({"path": path, "key": k, "value": entry.get("value"),
                                "old": old.get(k), "new": entry.get(k)})
    return out, changes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Recompute normalized fields of extracted files (dry run by default).")
    ap.add_argument("files", nargs="*", type=Path, help="extracted files (default: data/extracted/*.json)")
    ap.add_argument("--write", action="store_true", help="write the recomputed files")
    args = ap.parse_args(argv)
    files = args.files or sorted(ingest.OUT_DIR.glob("*.json"))
    lexicon = ingest._lexicon()
    grid = ingest.default_grid()
    report = {"write": args.write, "files_changed": 0, "changes": 0, "by_key": {}, "files": {}}
    for f in files:
        doc = json.loads(Path(f).read_text())
        new, changes = renormalize_doc(doc, lexicon, grid=grid)
        if not changes:
            continue
        report["files_changed"] += 1
        report["changes"] += len(changes)
        for c in changes:
            report["by_key"][c["key"]] = report["by_key"].get(c["key"], 0) + 1
        report["files"][Path(f).name] = changes
        if args.write:
            Path(f).write_text(dumps(new))
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
