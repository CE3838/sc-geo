"""Re-reads that call for page images: which queue items use them, and packets that point to the tiles."""

import json

import pytest

from extract import images, reread

SID = "ngmdb:6"
RECORD = {"id": SID, "title": "Geologic map", "year": 2001, "scale": 24000, "publisher": "U.S. Geological Survey",
          "citation": "C", "kind": "publication", "status": "published"}


@pytest.fixture
def env(tmp_path):
    cache = tmp_path / ".cache"
    (cache / "text").mkdir(parents=True)
    pdf = cache / "pdfs" / "ngmdb_6" / "01.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 stub")
    (cache / "text" / "ngmdb_6.json").write_text(json.dumps({"source_id": SID, "files": [
        {"url": "https://example.test/map.pdf", "path": str(pdf), "via": "pubs_usgs", "pages": 2, "first_page": 1}],
        "pages": [{"page": 1, "file": 0, "file_page": 1, "method": "ocr", "text": "A A' FEET 8-161 QTu Tc Cooper Formation sea level"},
                  {"page": 2, "file": 0, "file_page": 2, "method": "none", "text": ""}]}))
    calls = []

    def render(sid, pages, **kw):
        calls.append((sid, list(pages), kw.get("dpi"), kw.get("grid"), kw.get("crop")))
        return images.render(sid, pages, cache_dir=kw["cache_dir"], dpi=kw.get("dpi") or 100,
                             grid=kw.get("grid") or (2, 1), crop=kw.get("crop"),
                             renderer=lambda pdf, n, dpi, box, out: out.write_bytes(b"png"),
                             sizer=lambda pdf, n: (612.0, 792.0), native=lambda pdf, n: None)

    class Env:
        pass
    e = Env()
    e.cache, e.calls = cache, calls
    e.rkw = dict(cache_dir=cache, catalog={SID: RECORD}, extracted_dir=tmp_path / "extracted", scopes={},
                 image_render=render)
    return e


@pytest.mark.parametrize("item,want", [
    ({"reason": "map_face", "detail": "contour values"}, True),
    ({"reason": "image_pages", "detail": "figure"}, True),
    ({"reason": "subsurface_fields", "detail": "SUBSURFACE: tops in a table"}, True),
    ({"reason": "logs", "detail": "field logs"}, False),
    ({"reason": "logs", "detail": "logs drawn on cross section B-B'"}, True),
    ({"reason": "misread_digits", "detail": "Sections A-A' and B-B' digits"}, True),
    ({"reason": "logs", "detail": "x", "images": True}, True),
    ({"reason": "map_face", "detail": "x", "images": False}, False),
])
def test_which_queue_items_use_images(item, want):
    assert reread.wants_images(item) is want


def test_queue_items_say_whether_they_use_images(tmp_path):
    q = reread.build_queue(tmp_path, known=[{"source_id": "ngmdb:1", "pages": [1], "reason": "map_face",
                                             "detail": "contours"},
                                            {"source_id": "ngmdb:2", "pages": [3], "reason": "logs",
                                             "detail": "logs", "ocr": True}], old=None)
    by = {i["source_id"]: i for i in q["items"]}
    assert by["ngmdb:1"]["images"] is True and by["ngmdb:2"]["images"] is False


def test_reread_with_images_renders_tiles_and_the_packet_points_to_them(env):
    built = reread.build(SID, pages=[1], reason="cross section digits", images={"dpi": 100, "grid": (2, 1)},
                         **env.rkw)
    assert env.calls == [(SID, [1], 100, (2, 1), None)]
    m = built["images"]
    manifest = env.cache / "images" / "ngmdb_6" / "manifest.json"
    assert m["manifest"] == str(manifest) and manifest.exists()
    assert len(m["tiles"]) == 3 and all(t["page"] == 1 for t in m["tiles"])  # overview + 2 tiles
    assert built["estimated_tokens"] >= built["packets"][0]["estimated_tokens"] + m["estimated_tokens"]
    text = open(built["packets"][0]["path"]).read()
    assert "Image tiles" in text and str(manifest) in text and "extract/prompts/extract.md" in text
    for t in m["tiles"]:
        assert t["tile"] in text


def test_image_reread_keeps_pages_with_no_text(env):
    with pytest.raises(reread.RereadError, match="no text"):
        reread.build(SID, pages=[2], reason="r", **env.rkw)
    built = reread.build(SID, pages=[2], reason="figure", images=True, **env.rkw)
    assert built["packets"][0]["pages"] == [2] and built["no_text"] == [2]
    assert "=== PAGE 2" in open(built["packets"][0]["path"]).read()


def test_next_renders_images_for_items_that_need_them_and_keeps_going_without(env):
    q = {"items": [
        {"id": "a", "source_id": SID, "pages": [1], "reason": "map_face", "detail": "contours", "status": "pending"},
        {"id": "b", "source_id": SID, "pages": [1], "reason": "logs", "detail": "logs", "status": "pending"},
    ]}
    logs0 = []
    out = reread.next_rereads(q, n=5, log=logs0.append, **env.rkw)
    assert not logs0, logs0
    assert [o["queue_id"] for o in out] == ["a", "b"]
    assert out[0]["images"]["tiles"] and out[1].get("images") is None
    assert [c[0] for c in env.calls] == [SID]

    def broken(sid, pages, **kw):
        raise images.ImagesError("no cached PDF")
    logs = []
    out = reread.next_rereads({"items": [q["items"][0] | {"id": "c"}]}, n=5, log=logs.append,
                              **(env.rkw | {"image_render": broken}))
    assert out and out[0].get("images") is None and any("images" in m and "no cached PDF" in m for m in logs)


def test_images_command_can_build_the_reread_packet(monkeypatch, capsys):
    seen = {}

    def fake_build(sid, **kw):
        seen.update(kw, sid=sid)
        return {"id": sid, "citation": "C", "reason": kw["reason"], "pages": kw["pages"], "no_text": [], "ocred": [],
                "queue_ids": [], "packets": [], "estimated_tokens": 0}
    monkeypatch.setattr(reread, "build", fake_build)
    assert images.main([SID, "--pages", "1", "--grid", "3x2", "--reread", "--reason", "section A-A'"]) == 0
    assert seen["sid"] == SID and seen["pages"] == [1] and seen["reason"] == "section A-A'"
    assert seen["images"]["grid"] == (3, 2) and seen["images"]["overview"] is True
