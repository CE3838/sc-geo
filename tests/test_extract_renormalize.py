"""extract/renormalize.py: recompute derived fields of committed extractions, never the readings."""

import copy
import json
from pathlib import Path

import pytest

from extract import ingest, renormalize
from model.units import Lexicon

ROOT = Path(__file__).resolve().parent.parent
DERIVED = ("normalized", "derived_coordinates", "navd88")


def stored(value, page=3, **kw):
    return {"value": value, "source_id": "ngmdb:9", "page": page, "extraction_method": "llm", "confidence": 0.85,
            "inferred": False, "locator": None, "quote": f"quote of {value}", "quote_match": "exact",
            "text_method": "pdf_text", "verification": None, **kw}


DOC = {
    "source_id": "ngmdb:9", "title": "T", "year": 1985, "schema_version": 1, "updated_at": "2026-10-01T00:00:00+00:00",
    "summary": {"stored": 4}, "units": [], "structures": [], "references": [],
    "groundwater": [
        {"aquifer": stored("Floridan aquifer"),
         "head": stored("minimum of –97 ft", normalized={"min_ft": 97.0, "max_ft": None, "unit": "ft",
                                                         "approximate": False})},
        {"head": stored("about 2 feet below sea level",
                        normalized={"min_ft": 2.0, "max_ft": 2.0, "unit": "ft", "approximate": True})},
    ],
    "observations": [{"kind": "well", "location": stored("lat 324512, long 0795841", normalized={
        "lat": 32.7533, "lon": -79.9781, "format": "dms", "hemisphere_inferred": True})}],
}


def strip(node):
    if isinstance(node, dict):
        return {k: strip(v) for k, v in node.items() if k not in DERIVED}
    if isinstance(node, list):
        return [strip(v) for v in node]
    return node


def test_recomputes_normalized_and_reports_changes():
    before = copy.deepcopy(DOC)
    new, changes = renormalize.renormalize_doc(DOC, Lexicon([]))
    assert DOC == before  # the input is not modified
    heads = [g["head"]["normalized"] for g in new["groundwater"]]
    assert (heads[0]["min_ft"], heads[0]["max_ft"]) == (-97.0, None)
    assert (heads[1]["min_ft"], heads[1]["max_ft"]) == (-2.0, -2.0)
    got = {(c["path"], c["key"]) for c in changes}
    assert ("groundwater[0].head", "normalized") in got and ("groundwater[1].head", "normalized") in got
    assert ("observations[0].location", "derived_coordinates") in got
    # Heads get a derived NAVD88 value (no datum stated: kept as printed, approximate).
    assert ("groundwater[0].head", "navd88") in got
    h = new["groundwater"][0]["head"]["navd88"]
    assert (h["value"]["min_ft"], h["value"]["max_ft"]) == (-97.0, None) and h["approximate"] is True
    # "below sea level" (1985: NGVD29) needs a location and the grid: no NAVD88 value here.
    assert "navd88" not in new["groundwater"][1]["head"]
    assert ("groundwater[0].aquifer", "normalized") not in got
    # The old lenient parse of a location is dropped; derived_coordinates replaces it.
    assert ("observations[0].location", "normalized") in got
    assert "normalized" not in new["observations"][0]["location"]
    c = next(c for c in changes if c["path"] == "groundwater[1].head")
    assert c["old"]["min_ft"] == 2.0 and c["new"]["min_ft"] == -2.0 and c["value"] == "about 2 feet below sea level"


def test_never_changes_readings_quotes_pages_or_provenance():
    new, _ = renormalize.renormalize_doc(DOC, Lexicon([]))
    assert strip(new) == strip(DOC)
    assert new["groundwater"][0]["head"]["navd88"]["extraction_method"] == "datum_conversion"
    d = new["observations"][0]["location"]["derived_coordinates"]
    assert d["inferred"] is True and d["extraction_method"] == "inference" and d["page"] == 3


def test_idempotent():
    once, _ = renormalize.renormalize_doc(DOC, Lexicon([]))
    twice, changes = renormalize.renormalize_doc(once, Lexicon([]))
    assert changes == [] and twice == once


def test_cli_dry_run_writes_nothing_and_write_mode_writes(tmp_path, capsys):
    p = tmp_path / "ngmdb_9.json"
    text = renormalize.dumps(DOC)
    p.write_text(text)
    assert renormalize.main([str(p)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files_changed"] == 1 and report["changes"] >= 3
    assert p.read_text() == text
    assert renormalize.main([str(p), "--write"]) == 0
    capsys.readouterr()
    out = json.loads(p.read_text())
    assert out["groundwater"][0]["head"]["normalized"]["min_ft"] == -97.0
    assert strip(out) == strip(DOC) and out["updated_at"] == DOC["updated_at"]
    assert renormalize.main([str(p)]) == 0
    assert json.loads(capsys.readouterr().out)["changes"] == 0


FILES = sorted((ROOT / "data" / "extracted").glob("*.json"))


@pytest.fixture(scope="module")
def lexicon():
    return ingest._lexicon()


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_committed_files_keep_their_readings_and_format(path, lexicon):
    text = path.read_text()
    doc = json.loads(text)
    assert renormalize.dumps(doc) == text  # an unchanged file is written back byte for byte
    new, _ = renormalize.renormalize_doc(doc, lexicon)
    assert strip(new) == strip(doc)
