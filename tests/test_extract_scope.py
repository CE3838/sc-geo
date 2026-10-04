"""config/catalog_scope.json: records that are one chapter of a multi-paper volume."""

import json
from pathlib import Path

from extract import scope

ROOT = Path(__file__).resolve().parent.parent


def _doc(files):
    out, first = [], 1
    for url, n in files:
        out.append({"url": url, "pages": n, "first_page": first})
        first += n
    return {"files": out, "pages": [{"page": p} for p in range(1, first)]}


def test_pages_of_a_scoped_record():
    entry = {"pdf_pages": [3, 5], "extra_pages": [8]}
    assert scope.pages(entry, _doc([("https://x/v.pdf", 10)])) == {3, 4, 5, 8}


def test_url_guard_and_file_offset():
    entry = {"url": "https://x/v.pdf", "pdf_pages": [2, 3]}
    # The volume is the second file (after a 1-page plate): its PDF pages 2-3 are document pages 3-4.
    assert scope.pages(entry, _doc([("https://x/plate.pdf", 1), ("https://x/v.pdf", 5)])) == {3, 4}
    assert scope.pages(entry, _doc([("http://x/v.pdf", 5)])) == {2, 3}  # scheme does not matter
    # The record resolved to a different file (say its own chapter PDF): no scope applies.
    assert scope.pages(entry, _doc([("https://x/chapter-d.pdf", 5)])) is None


def test_for_record():
    scopes = {"ngmdb:1": {"pdf_pages": [2, 2], "note": "n"}}
    doc = _doc([("https://x/v.pdf", 4)])
    assert scope.for_record("ngmdb:1", doc, scopes) == {"pages": [2], "pdf_pages": [2, 2], "note": "n"}
    assert scope.for_record("ngmdb:2", doc, scopes) is None


def test_config_entries_are_well_formed():
    scopes = scope.load()
    assert scopes, "config/catalog_scope.json lists no records"
    catalog = {r["id"] for r in json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text())}
    for rid, e in scopes.items():
        assert rid in catalog, rid
        first, last = e["pdf_pages"]
        assert 1 <= first <= last, rid
        assert all(isinstance(p, int) and p >= 1 for p in e.get("extra_pages", [])), rid
        assert e.get("note") and e.get("url", "").startswith("https://"), rid
    # Chapters of one volume never overlap.
    by_url = {}
    for rid, e in scopes.items():
        by_url.setdefault(e["url"], []).append((e["pdf_pages"][0], e["pdf_pages"][1], rid))
    for chapters in by_url.values():
        chapters.sort()
        for a, b in zip(chapters, chapters[1:]):
            assert a[1] < b[0], (a[2], b[2])
