import json

from extract import next_batch
from harvest import pdfs

PILOT = [-80.47, 32.48, -79.30, 33.22]


def rec(rid, bbox):
    return {"id": rid, "title": f"T {rid}", "year": 2000, "publisher": "U.S. Geological Survey", "scale": 24000,
            "bbox": bbox, "citation": f"C {rid}", "kind": "map", "status": "published",
            "availability": {"pdf": [], "doi": None, "scgs_ftp": [], "gems_download": None}}


CAT = [rec("ngmdb:5", [-80.0, 32.80, -79.95, 32.85]),  # scanned map waiting for OCR
       rec("ngmdb:1", [-80.0, 32.75, -79.75, 33.0]), rec("ngmdb:2", [-80.1, 32.75, -79.85, 33.0]),
       rec("ngmdb:3", [-80.2, 32.75, -79.95, 33.0]), rec("ngmdb:4", [-82.5, 34.75, -82.25, 35.0])]


def fake_process(rec, fetcher, ckpt_dir, cache_dir, email, ocr="auto", resolve_only=False, log=print):
    sid = pdfs.safe_id(rec["id"])
    if rec["id"] == "ngmdb:2":
        ck = {"id": rec["id"], "status": "needs_access", "candidates": []}
    elif rec["id"] == "ngmdb:5":
        ck = {"id": rec["id"], "status": "needs_ocr", "candidates": [{"url": "u", "via": "ngmdb_scan"}]}
    else:
        text = {"source_id": rec["id"], "files": [{"url": "u", "pages": 1, "first_page": 1}],
                "pages": [{"page": 1, "file": 0, "file_page": 1, "method": "pdf_text",
                           "text": "Wando Formation, clayey sand, as much as 30 ft thick. " * 5, "raw": ""}]}
        (cache_dir / "text").mkdir(parents=True, exist_ok=True)
        (cache_dir / "text" / f"{sid}.json").write_text(json.dumps(text))
        ck = {"id": rec["id"], "status": "text", "candidates": [{"url": "u", "via": "catalog_pdf"}]}
    (ckpt_dir).mkdir(parents=True, exist_ok=True)
    (ckpt_dir / f"{sid}.json").write_text(json.dumps(ck))
    return ck


def test_next_batch_builds_missing_packets_in_priority_order(tmp_path, monkeypatch):
    monkeypatch.setattr(next_batch.pdfs, "process", fake_process)
    extracted = tmp_path / "data" / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "ngmdb_3.json").write_text("{}")  # already done
    batch = next_batch.next_batch(n=2, catalog=CAT, pilot_bbox=PILOT, cache_dir=tmp_path / ".cache",
                                  checkpoint_dir=tmp_path / ".checkpoints" / "pdfs", extracted_dir=extracted,
                                  review_dir=tmp_path / "data" / "review", log=lambda *a: None)
    assert [b["id"] for b in batch] == ["ngmdb:1", "ngmdb:4"]  # 5 needs OCR, 2 needs access, 3 done
    first = batch[0]
    assert first["packets"][0]["path"].endswith("ngmdb_1/packet-01.md")
    assert (tmp_path / ".cache" / "packets" / "ngmdb_1" / "packet-01.md").exists()
    assert first["packets"][0]["result_path"].endswith(".cache/results/ngmdb_1.packet-01.json")
    assert first["estimated_tokens"] > 0
    assert not list((tmp_path / "data").rglob("packet-*"))


def three_packet_text(cache_dir, sid):
    page = ("Wando Formation, clayey sand, as much as 30 ft thick. " * 40).strip()
    text = {"source_id": sid, "files": [{"url": "u", "pages": 3, "first_page": 1}],
            "pages": [{"page": n, "file": 0, "file_page": n, "method": "pdf_text", "text": page, "raw": ""}
                      for n in (1, 2, 3)]}
    (cache_dir / "text").mkdir(parents=True, exist_ok=True)
    (cache_dir / "text" / f"{pdfs.safe_id(sid)}.json").write_text(json.dumps(text))


def _batch(tmp_path, **kw):
    return next_batch.next_batch(catalog=CAT, pilot_bbox=PILOT, cache_dir=tmp_path / ".cache",
                                 checkpoint_dir=tmp_path / ".checkpoints" / "pdfs",
                                 extracted_dir=tmp_path / "data" / "extracted", review_dir=tmp_path / "data" / "review",
                                 log=lambda *a: None, packet_max_tokens=1500, **kw)


def test_started_documents_come_first_with_only_their_remaining_packets(tmp_path, monkeypatch):
    monkeypatch.setattr(next_batch.pdfs, "process", fake_process)
    three_packet_text(tmp_path / ".cache", "ngmdb:4")  # lowest priority in the queue
    extracted = tmp_path / "data" / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "ngmdb_4.json").write_text(json.dumps({"source_id": "ngmdb:4", "complete": False,
                                                        "blocks_done": ["1"]}))
    batch = _batch(tmp_path, n=2)
    assert batch[0]["id"] == "ngmdb:4" and batch[0]["started"] is True
    assert [p["blocks"] for p in batch[0]["packets"]] == [["2"], ["3"]]
    assert batch[1]["id"] == "ngmdb:1"


def test_token_budget_hands_out_part_of_a_document(tmp_path, monkeypatch):
    monkeypatch.setattr(next_batch.pdfs, "process", fake_process)
    three_packet_text(tmp_path / ".cache", "ngmdb:5")
    ck = tmp_path / ".checkpoints" / "pdfs"
    ck.mkdir(parents=True)
    (ck / "ngmdb_5.json").write_text(json.dumps({"id": "ngmdb:5", "status": "text"}))
    per_packet = _batch(tmp_path, n=1, ids=["ngmdb:5"])[0]["packets"][0]["estimated_tokens"]
    batch = _batch(tmp_path, n=5, max_tokens=int(per_packet * 2.5), ids=["ngmdb:5"])
    assert len(batch) == 1 and len(batch[0]["packets"]) == 2 and batch[0]["remaining_after"] == 1


def test_complete_and_legacy_files_are_done(tmp_path, monkeypatch):
    monkeypatch.setattr(next_batch.pdfs, "process", fake_process)
    extracted = tmp_path / "data" / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "ngmdb_1.json").write_text(json.dumps({"source_id": "ngmdb:1", "complete": True}))
    (extracted / "ngmdb_3.json").write_text(json.dumps({"source_id": "ngmdb:3"}))  # before per-packet ingest
    assert [b["id"] for b in _batch(tmp_path, n=5)] == ["ngmdb:4"]


def test_scoped_record_gets_only_its_pages_and_is_rebuilt_when_the_scope_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(next_batch.pdfs, "process", fake_process)
    three_packet_text(tmp_path / ".cache", "ngmdb:4")
    batch = _batch(tmp_path, n=5, ids=["ngmdb:4"], scopes={"ngmdb:4": {"pdf_pages": [2, 3], "note": "ch"}})
    assert [p["blocks"] for p in batch[0]["packets"]] == [["2"], ["3"]]
    assert batch[0]["scope"]["pages"] == [2, 3]
    index = tmp_path / ".cache" / "packets" / "ngmdb_4" / "index.json"
    assert json.loads(index.read_text())["blocks"] == ["2", "3"]
    batch = _batch(tmp_path, n=5, ids=["ngmdb:4"], scopes={"ngmdb:4": {"pdf_pages": [3, 3], "note": "ch"}})
    assert [p["blocks"] for p in batch[0]["packets"]] == [["3"]]
    batch = _batch(tmp_path, n=5, ids=["ngmdb:4"], scopes={})
    assert [p["blocks"] for p in batch[0]["packets"]] == [["1"], ["2"], ["3"]]
    assert batch[0]["scope"] is None


def test_scoped_record_is_done_when_its_pages_are_done(tmp_path, monkeypatch):
    monkeypatch.setattr(next_batch.pdfs, "process", fake_process)
    three_packet_text(tmp_path / ".cache", "ngmdb:4")
    extracted = tmp_path / "data" / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "ngmdb_4.json").write_text(json.dumps({"source_id": "ngmdb:4", "complete": False,
                                                        "blocks_done": ["2"]}))
    assert _batch(tmp_path, n=5, ids=["ngmdb:4"], scopes={"ngmdb:4": {"pdf_pages": [2, 2], "note": "ch"}}) == []


def test_excluded_records_are_never_handed_out(tmp_path, monkeypatch):
    monkeypatch.setattr(next_batch.pdfs, "process", fake_process)
    monkeypatch.setattr(next_batch.pdfs, "excluded_ids", lambda: {"ngmdb:1"})
    batch = next_batch.next_batch(n=5, catalog=CAT, pilot_bbox=PILOT, cache_dir=tmp_path / ".cache",
                                  checkpoint_dir=tmp_path / ".checkpoints" / "pdfs",
                                  extracted_dir=tmp_path / "data" / "extracted",
                                  review_dir=tmp_path / "data" / "review", log=lambda *a: None)
    assert "ngmdb:1" not in [b["id"] for b in batch]
