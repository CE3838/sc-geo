"""Guardrails from CLAUDE.md: no PDFs or internal data tracked in git."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [p for p in out.split("\0") if p]


def test_no_pdfs_tracked():
    pdfs = [p for p in tracked_files() if p.lower().endswith(".pdf")]
    assert pdfs == []


def test_no_internal_paths_tracked():
    blocked = ("internal/", "sc-geo-internal/", "data/raw/", "data/fulltext/")
    hits = [p for p in tracked_files() if p.startswith(blocked)]
    assert hits == []


# The state road agency's name and acronym, assembled from pieces so this file
# does not contain them itself.
_AGENCY = re.compile(
    r"\b" + "sc" + "dot" + r"\b|(?:south\s+carolina|s\.?\s?c\.?)\s+" + "depart" + r"ment\s+of\s+" + "transport" + "ation",
    re.I,
)


def test_agency_pattern_matches_its_forms():
    for text in ("x " + "SC" + "DOT y", "sc" + "dot.org", "South Carolina " + "Department of " + "Transportation",
                 "SC " + "department of " + "transportation"):
        assert _AGENCY.search(text), text
    assert not _AGENCY.search("US Census Bureau TIGER/Line roads")


def test_no_tracked_file_names_the_state_road_agency():
    hits = []
    for rel in tracked_files():
        path = ROOT / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue  # binary
        text = data.decode("utf-8", errors="ignore")
        if _AGENCY.search(text) or _AGENCY.search(rel):
            hits.append(rel)
    assert hits == []
