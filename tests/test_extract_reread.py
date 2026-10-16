"""Re-reading chosen pages of a document already read: packets from the cache, per-page replacement, history,
review queue, and the re-read queue."""

import json

import pytest

from extract import ingest, packets, reread
from model.units import Lexicon

SID = "ngmdb:5"
RECORD = {"id": SID, "title": "T", "year": 1990, "scale": None, "publisher": "U.S. Geological Survey",
          "citation": "C", "kind": "publication", "status": "published"}
PAGES = {
    1: "The Wando Formation is clayey sand, as much as 30 ft thick.",
    2: "The Ladson Formation is sand and clay of middle Pleistocene age.",
    3: "Auger hole AH-1 penetrated 12 ft of sand above the Ashley Formation. Top of the Ashley at -12 ft, "
       "relative to sea level.",
    4: "The Ashley Formation is a calcarenite of Oligocene age.",
}
INDEX = {"source_id": SID, "blocks": ["1", "2", "3", "4"],
         "packets": [{"file": "packet-01.md", "pages": [1, 2], "blocks": ["1", "2"], "estimated_tokens": 30},
                     {"file": "packet-02.md", "pages": [3, 4], "blocks": ["3", "4"], "estimated_tokens": 30}]}


def v(value, page, quote, **kw):
    return {"value": value, "page": page, "quote": quote, "inferred": False, **kw}


def result(packet_names, units=(), observations=(), surfaces=(), notes=None):
    r = {"schema_version": 1, "source_id": SID, "packets": packet_names, "units": list(units),
         "observations": list(observations), "structures": [], "groundwater": [], "references": [],
         "surfaces": list(surfaces)}
    if notes:
        r["notes"] = notes
    return r


WANDO = {"name": v("Wando Formation", 1, "The Wando Formation is clayey sand"),
         "thickness": v("as much as 30 ft", 1, "as much as 30 ft thick")}
LADSON = {"name": v("Ladson Formation", 2, "The Ladson Formation is sand and clay")}
ASHLEY = {"name": v("Ashley Formation", 4, "The Ashley Formation is a calcarenite")}
AH1_MISREAD = {"kind": "auger_hole", "label": v("AH-1", 3, "Auger hole AH-1"),
               "intervals": [{"bottom": v("17 ft", 3, "penetrated 12 ft of sand")}]}  # digit misread
AH1 = {"kind": "auger_hole", "label": v("AH-1", 3, "Auger hole AH-1"),
       "intervals": [{"bottom": v("12 ft", 3, "penetrated 12 ft of sand")}]}
ASHLEY_TOP = {"surface": v("top of the Ashley", 3, "Top of the Ashley at -12 ft"),
              "boundary": v("top", 3, "Top of the Ashley"),
              "elevation": v("-12 ft", 3, "Top of the Ashley at -12 ft"),
              "datum": v("sea level", 3, "relative to sea level"),
              "observation": v("AH-1", 3, "Auger hole AH-1"),
              "method": v("measured", 3, "Auger hole AH-1 penetrated")}


@pytest.fixture
def env(tmp_path):
    cache = tmp_path / ".cache"
    text = cache / "text"
    text.mkdir(parents=True)
    pdf = tmp_path / "doc.pdf"
    (text / "ngmdb_5.json").write_text(json.dumps({"source_id": SID, "files": [
        {"url": "https://pubs.usgs.gov/x/report.pdf", "path": str(pdf), "via": "pubs_usgs", "pages": 5,
         "first_page": 1}],
        "pages": [{"page": n, "file": 0, "file_page": n, "method": "pdf_text", "text": t, "raw": t}
                  for n, t in PAGES.items()]
        + [{"page": 5, "file": 0, "file_page": 5, "method": "none", "text": "", "raw": "", "needs_ocr": True}]}))
    pk = cache / "packets" / "ngmdb_5"
    pk.mkdir(parents=True)
    (pk / "index.json").write_text(json.dumps(INDEX))
    kw = dict(text_dir=text, packets_dir=cache / "packets", out_dir=tmp_path / "data" / "extracted",
              review_dir=tmp_path / "data" / "review", done_dir=tmp_path / ".checkpoints" / "extract",
              catalog={SID: RECORD}, lexicon=Lexicon([]))

    class Env:
        pass
    e = Env()
    e.tmp, e.cache, e.kw = tmp_path, cache, kw
    e.rkw = dict(cache_dir=cache, catalog={SID: RECORD}, extracted_dir=kw["out_dir"], scopes={})

    def run(res, name, verify=None):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(res))
        vp = None
        if verify:
            vp = tmp_path / f"{name}.verify.json"
            vp.write_text(json.dumps(verify))
        return ingest.ingest([p], verify_path=vp, **kw)
    e.run = run
    e.out = lambda: json.loads((kw["out_dir"] / "ngmdb_5.json").read_text())
    e.review = lambda: json.loads((kw["review_dir"] / "queue.json").read_text())["items"]
    return e


def _read_both(env):
    env.run(result(["packet-01"], [WANDO, LADSON]), "p1")
    env.run(result(["packet-02"], [ASHLEY], [AH1_MISREAD]), "p2")
    assert env.out()["complete"] is True


# --- building re-read packets -------------------------------------------------------

def test_reread_builds_packets_for_chosen_pages_from_the_cache(env):
    _read_both(env)
    built = reread.build(SID, pages=[3], reason="misread digits on page 3", **env.rkw)
    assert [p["packet"] for p in built["packets"]] == ["reread-01"]
    p = built["packets"][0]
    assert p["pages"] == [3] and p["blocks"] == ["3"]
    text = open(p["path"]).read()
    assert "=== PAGE 3 (pdf_text) ===" in text and "=== PAGE 4" not in text and "=== PAGE 1" not in text
    assert "misread digits on page 3" in text
    assert "Re-read" in text and "replace" in text
    assert p["result_path"].endswith("ngmdb_5.reread-01.json")
    index = json.loads((env.cache / "packets" / "ngmdb_5" / "reread" / "index.json").read_text())
    assert index["packets"][0]["reason"] == "misread digits on page 3"
    # the normal packets are untouched
    assert json.loads((env.cache / "packets" / "ngmdb_5" / "index.json").read_text()) == INDEX


def test_reread_by_packet_name_uses_that_packets_pages(env):
    _read_both(env)
    built = reread.build(SID, packet_names=["packet-02"], reason="new subsurface fields", **env.rkw)
    assert built["packets"][0]["pages"] == [3, 4]


def test_reread_never_downloads(env, monkeypatch):
    (env.cache / "text" / "ngmdb_5.json").unlink()
    import harvest.pdfs as hp
    monkeypatch.setattr(hp, "process", lambda *a, **k: pytest.fail("downloaded"))
    monkeypatch.setattr(hp, "HttpFetcher", lambda *a, **k: pytest.fail("downloaded"))
    with pytest.raises(reread.RereadError, match="no cached text"):
        reread.build(SID, pages=[1], reason="r", **env.rkw)


def test_same_request_reuses_its_packets(env):
    a = reread.build(SID, pages=[3], reason="r", **env.rkw)
    b = reread.build(SID, pages=[3], reason="r", **env.rkw)
    c = reread.build(SID, pages=[4], reason="r", **env.rkw)
    assert a["packets"][0]["packet"] == b["packets"][0]["packet"] == "reread-01"
    assert c["packets"][0]["packet"] == "reread-02"


def test_pages_without_text_are_left_out_unless_ocred(env):
    built = reread.build(SID, pages=[3, 5], reason="r", **env.rkw)
    assert built["no_text"] == [5] and built["packets"][0]["pages"] == [3]
    with pytest.raises(reread.RereadError, match="no text"):
        reread.build(SID, pages=[5], reason="r", **env.rkw)


def test_ocr_option_reads_chosen_pages_from_the_cached_pdf(env):
    (env.tmp / "doc.pdf").write_bytes(b"%PDF-1.4 stub")
    calls = []

    def fake_ocr(path, n):
        calls.append(n)
        return "Well W-9 log: 0-20 ft clayey sand.", "Well W-9 log: 0-20 ft clayey sand."
    built = reread.build(SID, pages=[5], reason="logs are images", ocr=fake_ocr, **env.rkw)
    assert calls == [5]
    assert built["packets"][0]["pages"] == [5] and built["ocred"] == [5]
    doc = json.loads((env.cache / "text" / "ngmdb_5.json").read_text())
    page = next(p for p in doc["pages"] if p["page"] == 5)
    assert page["method"] == "ocr" and "W-9" in page["text"] and page.get("reread_ocr")
    # a page whose text layer holds only a caption is OCRed too, and keeps the caption
    calls.clear()
    reread.build(SID, pages=[2], reason="caption only", ocr=fake_ocr, **env.rkw)
    page = next(p for p in json.loads((env.cache / "text" / "ngmdb_5.json").read_text())["pages"] if p["page"] == 2)
    assert calls == [2] and "Ladson" in page["text"] and "W-9" in page["text"]
    # OCRed once: asking again does not OCR again
    calls.clear()
    reread.build(SID, pages=[2], reason="caption only", ocr=fake_ocr, **env.rkw)
    assert calls == []


def test_ocr_needs_the_cached_pdf(env):
    with pytest.raises(reread.RereadError, match="cached PDF"):
        reread.build(SID, pages=[5], reason="r", ocr=lambda p, n: ("x", "x"), **env.rkw)


def test_scope_limits_rereads(env):
    scopes = {SID: {"url": "https://pubs.usgs.gov/x/report.pdf", "pdf_pages": [1, 2], "note": "Chapter A"}}
    with pytest.raises(reread.RereadError, match="outside"):
        reread.build(SID, pages=[3], reason="r", **(env.rkw | {"scopes": scopes}))


def test_parse_pages():
    assert reread.parse_pages("1,3-5, 9") == [1, 3, 4, 5, 9]
    assert reread.parse_pages("280–282, 300") == [280, 281, 282, 300]


# --- ingesting a re-read ----------------------------------------------------------------

def test_reread_replaces_values_on_its_pages_and_keeps_history(env):
    env.run(result(["packet-01"], [WANDO, LADSON]), "p1")
    ah9 = {"kind": "auger_hole", "label": v("AH-9", 3, "Auger hole AH-9")}  # quote not on the page: review item
    env.run(result(["packet-02"], [ASHLEY], [AH1_MISREAD, ah9]), "p2")
    assert [i["value"] for i in env.review()] == ["AH-9"]
    reread.build(SID, pages=[3], reason="misread digits on page 3", queue_ids=["q1"], **env.rkw)
    bad = {"kind": "auger_hole", "label": v("AH-2", 3, "Auger hole AH-2")}   # not on the page: review item
    s = env.run(result(["reread-01"], [], [AH1, bad], [ASHLEY_TOP]), "rr")
    assert s["complete"] is True
    doc = env.out()
    obs = doc["observations"]
    assert [o["intervals"][0]["bottom"]["value"] for o in obs] == ["12 ft"]       # corrected
    assert doc["surfaces"][0]["elevation"]["value"] == "-12 ft"                    # new field
    assert [u["name"]["value"] for u in doc["units"]] == ["Wando Formation", "Ladson Formation", "Ashley Formation"]
    assert doc["packets"] == ["packet-01", "packet-02"]                            # re-reads are not packets
    assert doc["complete"] is True and doc["blocks_done"] == ["1", "2", "3", "4"]
    h = doc["history"][-1]
    assert h["reason"] == "misread digits on page 3" and h["packets"] == ["reread-01"] and h["pages"] == [3]
    assert h["at"][:4].isdigit()
    old = h["replaced"]
    assert old[0]["section"] == "observations"
    assert old[0]["record"]["intervals"][0]["bottom"]["value"] == "17 ft"
    assert old[0]["record"]["kind"] == "auger_hole"
    last = doc["ingests"][-1]
    assert last["reread"]["reason"] == "misread digits on page 3" and last["reread"]["queue_ids"] == ["q1"]
    items = env.review()
    assert [i["value"] for i in items if i["page"] == 3] == ["AH-2"]     # old item dropped, new one added


def test_reread_on_a_split_page_replaces_all_its_parts(env):
    long = ("Auger hole AH-1 penetrated 12 ft of sand. " + "Filler text about the sand. " * 400).strip()
    doc = json.loads((env.cache / "text" / "ngmdb_5.json").read_text())
    for p in doc["pages"]:
        if p["page"] == 3:
            p["text"] = p["raw"] = long
    (env.cache / "text" / "ngmdb_5.json").write_text(json.dumps(doc))
    index = dict(INDEX, blocks=["1", "2", "3.1/2", "3.2/2", "4"])
    index["packets"] = [INDEX["packets"][0], {"file": "packet-02.md", "pages": [3], "blocks": ["3.1/2"],
                                              "estimated_tokens": 30},
                        {"file": "packet-03.md", "pages": [3, 4], "blocks": ["3.2/2", "4"], "estimated_tokens": 30}]
    (env.cache / "packets" / "ngmdb_5" / "index.json").write_text(json.dumps(index))
    env.run(result(["packet-01"], [WANDO]), "a")
    env.run(result(["packet-02"], [], [AH1_MISREAD]), "b")
    env.run(result(["packet-03"], [ASHLEY]), "c")
    built = reread.build(SID, pages=[3], reason="r", max_tokens=1000, **env.rkw)
    assert len(built["packets"]) > 1                       # the long page needs several packets
    names = [p["packet"] for p in built["packets"]]
    env.run(result(names, [], [AH1]), "rr")
    obs = env.out()["observations"]
    assert [o["intervals"][0]["bottom"]["value"] for o in obs] == ["12 ft"]


def test_verify_pass_applies_to_a_reread(env):
    _read_both(env)
    reread.build(SID, pages=[3], reason="r", **env.rkw)
    res = result(["reread-01"], [], [AH1])
    plan = ingest.verify_sample(res)
    assert plan
    ver = {"source_id": SID, "checks": [{"path": "observations[0].intervals[0].bottom", "verdict": "agree"}]}
    env.run(res, "rr", verify=ver)
    assert env.out()["observations"][0]["intervals"][0]["bottom"]["verification"] == "agree"


def test_reread_quotes_are_checked_like_a_normal_read(env):
    _read_both(env)
    reread.build(SID, pages=[3], reason="r", **env.rkw)
    s = env.run(result(["reread-01"], [], [{"kind": "auger_hole", "label": v("AH-7", 3, "Auger hole AH-7")}]), "rr")
    assert s["quote_not_found"] == 1 and s["stored"] == 0
    assert env.out()["observations"] == []
    assert env.out()["history"][-1]["replaced"]   # the old AH-1 is in the history, not lost


def test_reingesting_a_packet_also_keeps_what_it_replaced(env):
    env.run(result(["packet-01"], [WANDO, LADSON]), "p1")
    env.run(result(["packet-01"], [WANDO]), "p1-again")
    h = env.out()["history"]
    assert h[-1]["reason"] == "re-ingest of packet-01"
    names = [r["record"]["name"]["value"] for r in h[-1]["replaced"]]
    assert "Ladson Formation" in names


def test_first_reads_write_no_history(env):
    _read_both(env)
    assert "history" not in env.out()


def test_notes_lines_are_not_repeated(env):
    env.run(result(["packet-01"], [WANDO], notes="SUBSURFACE: p. 1 has no section."), "a")
    env.run(result(["packet-01"], [WANDO], notes="SUBSURFACE: p. 1 has no section."), "b")
    assert env.out()["notes"] == "SUBSURFACE: p. 1 has no section."


def test_unknown_reread_packet_is_refused(env):
    _read_both(env)
    with pytest.raises(ingest.IngestError, match="reread-07"):
        env.run(result(["reread-07"], [], [AH1]), "rr")


# --- the re-read queue ---------------------------------------------------------------------

def _extracted(d, sid, notes, **extra):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{packets.safe_id(sid)}.json").write_text(json.dumps(
        {"source_id": sid, "complete": True, "notes": notes, "blocks_done": ["1"], "blocks_total": 1,
         "units": [], "observations": [], "surfaces": [], "contours": [], "sections": [], "ingests": [], **extra}))


def test_queue_from_subsurface_notes_and_known_rereads(tmp_path):
    ex = tmp_path / "extracted"
    _extracted(ex, "ngmdb:1", "Single OCR page.\nSUBSURFACE: p. 1 has cross section A-A' (vertical exaggeration 50).")
    _extracted(ex, "ngmdb:2", "SUBSURFACE: pages 3-4 give the top of the Cooper Marl.\n"
                              "SUBSURFACE: pages 3-4 give the top of the Cooper Marl.")
    _extracted(ex, "ngmdb:3", "SUBSURFACE: margins at 10-18 ft, no page given.", blocks_done=["1", "2"])
    _extracted(ex, "ngmdb:4", "No subsurface notes here.")
    _extracted(ex, "ngmdb:8", "SUBSURFACE: none; no cross section, structure contours or logs (page 1).")
    _extracted(ex, "ngmdb:6", "SUBSURFACE: page 1 contours.",
               contours=[{"values": {"value": "-20", "page": 1, "quote": "-20", "source_id": "ngmdb:6"}}])
    known = [{"source_id": "ngmdb:9", "pages": [79, 80], "reason": "logs", "detail": "piezometer logs", "ocr": True}]
    q = reread.build_queue(ex, known=known, old=None)
    by = {(i["source_id"], tuple(i["pages"])): i for i in q["items"]}
    assert set(by) == {("ngmdb:1", (1,)), ("ngmdb:2", (3, 4)), ("ngmdb:3", (1, 2)), ("ngmdb:9", (79, 80))}
    assert by[("ngmdb:1", (1,))]["reason"] == "subsurface_fields"
    assert by[("ngmdb:1", (1,))]["detail"].startswith("SUBSURFACE: p. 1 has cross section")
    assert by[("ngmdb:9", (79, 80))]["origin"] == "ROADMAP 1.9" and by[("ngmdb:9", (79, 80))]["ocr"] is True
    assert all(i["status"] == "pending" for i in q["items"])
    assert q["count"] == 4 and q["by_reason"] == {"subsurface_fields": 3, "logs": 1}
    ids = [i["id"] for i in q["items"]]
    assert len(set(ids)) == len(ids)


def test_queue_marks_items_done_and_keeps_manual_entries(tmp_path):
    ex = tmp_path / "extracted"
    _extracted(ex, "ngmdb:1", "SUBSURFACE: p. 1 has a section.")
    q = reread.build_queue(ex, known=[], old=None)
    item = q["items"][0]
    manual = {"id": "ngmdb:7:manual:p2", "source_id": "ngmdb:7", "pages": [2], "reason": "misread_digits",
              "detail": "OCR read 5 as S", "origin": "manual", "status": "pending", "added_at": "2026-10-01"}
    q["items"].append(manual)
    d = json.loads((ex / "ngmdb_1.json").read_text())
    d["ingests"].append({"at": "2026-10-09T00:00:00+00:00", "packets": ["reread-01"],
                         "reread": {"reason": "x", "queue_ids": [item["id"]], "pages": [1]}})
    (ex / "ngmdb_1.json").write_text(json.dumps(d))
    q2 = reread.build_queue(ex, known=[], old=q)
    by = {i["id"]: i for i in q2["items"]}
    assert by[item["id"]]["status"] == "done" and by[item["id"]]["done_at"].startswith("2026-10-09")
    assert by[item["id"]]["added_at"] == item["added_at"]
    assert by[manual["id"]]["status"] == "pending"
    assert q2["pending"] == 1


def test_next_hands_out_pending_rereads(env, monkeypatch):
    _read_both(env)
    q = {"items": [
        {"id": "a", "source_id": "ngmdb:404", "pages": [1], "reason": "logs", "detail": "d", "status": "pending", "origin": "manual"},
        {"id": "b", "source_id": SID, "pages": [3], "reason": "subsurface_fields", "detail": "SUBSURFACE: p. 3",
         "status": "pending", "origin": "manual"},
        {"id": "c", "source_id": SID, "pages": [1], "reason": "logs", "detail": "d", "status": "done"},
    ]}
    logs = []
    out = reread.next_rereads(q, n=5, log=logs.append, **(env.rkw | {"catalog": {SID: RECORD}}))
    assert [o["queue_id"] for o in out] == ["b"]
    assert out[0]["packets"][0]["pages"] == [3]
    assert any("ngmdb:404" in m and "no cached text" in m for m in logs)
    idx = json.loads((env.cache / "packets" / "ngmdb_5" / "reread" / "index.json").read_text())
    assert idx["packets"][0]["queue_ids"] == ["b"]
    # after the re-read is ingested, the item is done
    env.run(result([out[0]["packets"][0]["packet"]], [], [AH1]), "rr")
    q2 = reread.build_queue(env.kw["out_dir"], known=[], old=q)
    assert {i["id"]: i["status"] for i in q2["items"]}["b"] == "done"


def test_committed_queue_lists_the_known_rereads():
    q = json.loads((reread.QUEUE_PATH).read_text())
    keys = {(i["source_id"], tuple(i["pages"])) for i in q["items"]}
    assert ("ngmdb:74345", (18,)) in keys
    assert ("ngmdb:74350", (280, 281, 282, 300, 301)) in keys
    assert ("ngmdb:96652", (79, 80, 81, 82)) in keys
    assert any(s == "ngmdb:42961" for s, _ in keys) and any(s == "ngmdb:27394" for s, _ in keys)
    assert q["count"] == len(q["items"])
