"""Guardrails from CLAUDE.md: no PDFs or internal data tracked in git."""

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
