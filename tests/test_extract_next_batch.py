import json

from extract import next_batch
from harvest import pdfs

PILOT = [-80.47, 32.48, -79.30, 33.22]


def rec(rid, bbox):
    return {"id": rid, "title": f"T {rid}", "year": 2000, "publisher": "U.S. Geological Survey", "scale": 24000,
            "bbox": bbox, "citation": f"C {rid}", "kind": "map", "status": "published",
            "availability": {"pdf": [], "doi": None, "scgs_ftp": [], "gems_download": None}}


CAT = [rec("ngmdb:1", [-80.0, 32.75, -79.75, 33.0]), rec("ngmdb:2", [-80.1, 32.75, -79.85, 33.0]),
       rec("ngmdb:3", [-80.2, 32.75, -79.95, 33.0]), rec("ngmdb:4", [-82.5, 34.75, -82.25, 35.0])]


def fake_process(rec, fetcher, ckpt_dir, cache_dir, email, ocr="auto", resolve_only=False, log=print):
    sid = pdfs.safe_id(rec["id"])
    if rec["id"] == "ngmdb:2":
        ck = {"id": rec["id"], "status": "needs_access", "candidates": []}
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
    assert [b["id"] for b in batch] == ["ngmdb:1", "ngmdb:4"]  # 2 needs access, 3 done
    first = batch[0]
    assert first["packets"][0]["path"].endswith("ngmdb_1/packet-01.md")
    assert (tmp_path / ".cache" / "packets" / "ngmdb_1" / "packet-01.md").exists()
    assert first["result_path"].endswith(".cache/results/ngmdb_1.json")
    assert first["estimated_tokens"] > 0
    assert not list((tmp_path / "data").rglob("packet-*"))
