"""Checks on committed extraction output (data/extracted, data/review)."""

import json
from pathlib import Path

import pytest

from model.provenance import ExtractionMethod, StoredValue

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted((ROOT / "data" / "extracted").glob("*.json"))


def _values(node):
    if isinstance(node, dict):
        if {"value", "source_id", "extraction_method", "confidence"} <= node.keys():
            yield node
            return
        for v in node.values():
            yield from _values(v)
    elif isinstance(node, list):
        for v in node:
            yield from _values(v)


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_extracted_values_have_provenance_and_short_quotes(path):
    doc = json.loads(path.read_text())
    values = list(_values({k: doc[k] for k in ("units", "observations", "structures", "groundwater", "references")}))
    # A document that holds nothing to extract (a program summary, a surface-water study) is
    # committed once, complete and with a note saying why, so it is not handed out again.
    if not values:
        assert doc.get("complete") and doc.get("notes"), "an empty extraction needs complete=true and notes"
    for v in values:
        sv = StoredValue.from_dict(v)
        assert sv.source_id == doc["source_id"]
        assert sv.extraction_method is ExtractionMethod.LLM and sv.page is not None
        assert 0 < len(v["quote"]) <= 400
        assert v["quote_match"] in ("exact", "ocr", "fuzzy")
    assert all("path" not in f for f in doc["files"])  # no local paths


def test_data_holds_no_full_text():
    for p in (ROOT / "data").rglob("*"):
        if p.is_file():
            assert p.suffix.lower() not in (".pdf", ".txt", ".md") or p.name == "README.md", p
            assert p.stat().st_size < 5_000_000, f"{p} is suspiciously large for derived data"
