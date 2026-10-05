import json

from extract import prep

from tests.test_extract_next_batch import CAT, PILOT, fake_process


def write_list(tmp_path, ids):
    path = tmp_path / "reading_list.json"
    path.write_text(json.dumps({"about": "x", "ids": ids}))
    return path


def test_todo_skips_finished_and_needs_access_keeps_started(tmp_path):
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "ngmdb_1.json").write_text(json.dumps({"complete": True}))
    (extracted / "ngmdb_2.json").write_text(json.dumps({"complete": False}))
    review = tmp_path / "review"
    review.mkdir()
    (review / "needs_access.json").write_text(json.dumps({"records": [{"id": "ngmdb:3"}]}))
    path = write_list(tmp_path, ["ngmdb:1", "ngmdb:2", "ngmdb:3", "ngmdb:4"])
    assert prep.todo(path, extracted, review) == ["ngmdb:2", "ngmdb:4"]


def test_prepare_builds_packets_one_at_a_time_without_handing_out(tmp_path, monkeypatch):
    monkeypatch.setattr(prep.next_batch.pdfs, "process", fake_process)
    lines = []
    status = prep.prepare(["ngmdb:1", "ngmdb:2", "ngmdb:5"], catalog=CAT, pilot_bbox=PILOT,
                          cache_dir=tmp_path / ".cache", checkpoint_dir=tmp_path / ".checkpoints" / "pdfs",
                          extracted_dir=tmp_path / "extracted", review_dir=tmp_path / "review",
                          ocr=None, log=lines.append)
    assert status == {"ngmdb:1": "READY", "ngmdb:2": "NOT-READY", "ngmdb:5": "NOT-READY"}
    assert (tmp_path / ".cache" / "packets" / "ngmdb_1" / "packet-01.md").exists()
    assert any(line.startswith("READY ngmdb:1") for line in lines)
    assert not (tmp_path / "extracted").exists() or not list((tmp_path / "extracted").iterdir())


def test_reading_list_ids_are_in_the_catalog():
    ids = json.loads(prep.READING_LIST.read_text())["ids"]
    catalog = {r["id"] for r in json.loads((prep.ROOT / "data" / "catalog" / "sc_catalog.json").read_text())}
    assert ids and len(ids) == len(set(ids))
    assert set(ids) <= catalog
