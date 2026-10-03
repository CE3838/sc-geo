import json

from extract import packets, triage

TOC = """CONTENTS
Abstract .......................................... 1
Introduction ...................................... 2
Stratigraphy ...................................... 5
Wando Formation ................................... 9
References cited .................................. 30
"""

INDEX = """INDEX
Ashley Formation, 12, 14
Charleston, 3, 5, 9
Cooper Group, 11
Wando Formation, 22, 23, 40
Ten Mile Hill beds, 18
"""

REFS = """REFERENCES CITED
Cooke, C.W., 1936, Geology of the Coastal Plain of South Carolina: U.S. Geological Survey Bulletin 867, 196 p.
McCartan, Lucy, Lemon, E.M., Jr., and Weems, R.E., 1984, Geologic map of the area between Charleston and
   Orangeburg, South Carolina: U.S. Geological Survey Miscellaneous Investigations Series Map I-1472.
Weems, R.E., and Lemon, E.M., Jr., 1984, Geologic map of the Mount Holly quadrangle: GQ-1579.
"""

CONTENT = """The Wando Formation consists of clayey sand and sand, as much as 30 ft thick, that underlies
the lowest terraces near Charleston. Auger hole 12 penetrated 4 ft of yellowish-brown (10YR 5/6) sand.
""" * 3


def test_triage_kinds():
    assert triage.classify("", 3, 50)["kind"] == "blank"
    assert triage.classify("", 3, 50)["keep"] is False
    assert triage.classify(TOC, 2, 50) | {} == triage.classify(TOC, 2, 50)
    assert triage.classify(TOC, 2, 50)["kind"] == "toc" and not triage.classify(TOC, 2, 50)["keep"]
    assert triage.classify(INDEX, 49, 50)["kind"] == "index" and not triage.classify(INDEX, 49, 50)["keep"]
    refs = triage.classify(REFS, 45, 50)
    assert refs["kind"] == "references" and refs["keep"] is True  # references are extracted too
    body = triage.classify(CONTENT, 9, 50)
    assert body["kind"] == "content" and body["keep"] and body["score"] > refs["score"]


def test_triage_title_page_kept():
    t = triage.classify("Geology of the Charleston Quadrangle\nBy R.E. Weems\n1993", 1, 50)
    assert t["kind"] == "title" and t["keep"]


def test_triage_needs_ocr_page_is_skipped():
    t = triage.classify("", 1, 1, method="none")
    assert t["kind"] == "needs_ocr" and not t["keep"]


RECORD = {"id": "ngmdb:10009", "title": "Geology of the Cainhoy quadrangle", "year": 1993, "scale": 24000,
          "publisher": "U.S. Geological Survey", "citation": "Weems, R.E., and Lemon, E.M., 1993, Geology ...",
          "kind": "map"}


def _doc(pages):
    return {"source_id": "ngmdb:10009", "files": [{"url": "https://x/a.pdf", "pages": len(pages), "first_page": 1}],
            "pages": [{"page": i + 1, "file": 0, "file_page": i + 1, "text": t, "raw": t,
                       "method": "pdf_text" if t else "none", "needs_ocr": not t} for i, t in enumerate(pages)]}


def test_build_packets_keeps_pages_and_header():
    doc = _doc(["Title page\nGeology of the Cainhoy quadrangle", TOC, CONTENT, " \n ", REFS, INDEX, ""])
    out = packets.build(doc, RECORD, max_tokens=40000)
    assert len(out) == 1
    p = out[0]
    assert p["pages"] == [1, 3, 5]
    assert "=== PAGE 3 (pdf_text) ===" in p["text"]
    assert "=== PAGE 2" not in p["text"] and "=== PAGE 6" not in p["text"]
    assert "Weems, R.E., and Lemon" in p["text"]  # citation in header
    assert "ngmdb:10009" in p["text"] and "1:24,000" in p["text"]
    assert p["skipped"] == {"toc": [2], "blank": [4], "index": [6], "needs_ocr": [7]}


def test_build_packets_splits_under_budget():
    long_page = ("Sand, clayey, gray. " * 400).strip()  # ~8000 chars
    doc = _doc([long_page] * 12)
    out = packets.build(doc, RECORD, max_tokens=5000, chars_per_token=4)
    assert len(out) > 1
    assert all(len(p["text"]) <= 5000 * 4 for p in out)
    assert sorted(n for p in out for n in p["pages"]) == list(range(1, 13))
    assert [p["packet"] for p in out] == [f"packet-{i:02d}" for i in range(1, len(out) + 1)]
    assert all(p["of"] == len(out) for p in out)


def test_oversized_page_split_into_parts():
    doc = _doc([("Clay and sand. " * 3000).strip()])  # ~45000 chars
    out = packets.build(doc, RECORD, max_tokens=4000, chars_per_token=4)
    assert len(out) >= 3
    assert all(len(p["text"]) <= 16000 for p in out)
    assert "(pdf_text, part 1 of" in out[0]["text"]
    assert all(p["pages"] == [1] for p in out)


def test_layout_whitespace_is_compressed():
    doc = _doc(["Unit" + " " * 40 + "Thickness\nQw" + " " * 40 + "30 ft" + " " * 20 + "\n\n\n\n\nWando Formation, clayey sand"])
    text = packets.build(doc, RECORD)[0]["text"]
    assert "Unit   Thickness" in text and "\n\n\n" not in text.split("=== PAGE 1")[1]


def test_write_packets_only_under_cache(tmp_path):
    doc = _doc([CONTENT])
    out = packets.build(doc, RECORD)
    paths = packets.write(out, RECORD, tmp_path / ".cache" / "packets")
    assert all(str(p).startswith(str(tmp_path / ".cache" / "packets")) for p in paths)
    index = json.loads((tmp_path / ".cache" / "packets" / "ngmdb_10009" / "index.json").read_text())
    assert index["source_id"] == "ngmdb:10009" and index["packets"][0]["file"] == "packet-01.md"
    assert index["estimated_tokens"] > 0


def test_safe_id():
    assert packets.safe_id("ngmdb:10009") == "ngmdb_10009"
    assert packets.safe_id("scgs-draft:ab/c d") == "scgs-draft_ab_c_d"
