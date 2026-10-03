"""Long documents: results for a subset of packets merge into one extracted file."""

import json

import pytest

from extract import ingest
from model.units import Lexicon

RECORD = {"id": "ngmdb:5", "title": "T", "year": 1990, "scale": None, "publisher": "U.S. Geological Survey",
          "citation": "C", "kind": "publication", "status": "published"}
PAGES = {
    1: "The Wando Formation is clayey sand, as much as 30 ft thick.",
    2: "The Ladson Formation is sand and clay of middle Pleistocene age.",
    3: "Auger hole AH-1 penetrated 12 ft of sand above the Ashley Formation.",
    4: "The Ashley Formation is a calcarenite of Oligocene age.",
}
INDEX = {"source_id": "ngmdb:5", "blocks": ["1", "2", "3", "4"],
         "packets": [{"file": "packet-01.md", "pages": [1, 2], "blocks": ["1", "2"], "estimated_tokens": 30},
                     {"file": "packet-02.md", "pages": [3, 4], "blocks": ["3", "4"], "estimated_tokens": 30}]}


def v(value, page, quote, **kw):
    return {"value": value, "page": page, "quote": quote, "inferred": False, **kw}


def result(packets, units=(), observations=()):
    return {"schema_version": 1, "source_id": "ngmdb:5", "packets": packets, "units": list(units),
            "observations": list(observations), "structures": [], "groundwater": [], "references": []}


WANDO = {"name": v("Wando Formation", 1, "The Wando Formation is clayey sand"),
         "thickness": v("as much as 30 ft", 1, "as much as 30 ft thick")}
LADSON = {"name": v("Ladson Formation", 2, "The Ladson Formation is sand and clay")}
ASHLEY = {"name": v("Ashley Formation", 4, "The Ashley Formation is a calcarenite"),
          "age": v("Oligocene", 4, "calcarenite of Oligocene age")}
AH1 = {"kind": "auger_hole", "label": v("AH-1", 3, "Auger hole AH-1"),
       "intervals": [{"bottom": v("12 ft", 3, "penetrated 12 ft of sand")}]}


@pytest.fixture
def env(tmp_path):
    text = tmp_path / ".cache" / "text"
    text.mkdir(parents=True)
    (text / "ngmdb_5.json").write_text(json.dumps({"source_id": "ngmdb:5", "files": [
        {"url": "https://pubs.usgs.gov/x/report.pdf", "via": "pubs_usgs", "pages": 4, "first_page": 1}],
        "pages": [{"page": n, "file": 0, "file_page": n, "method": "pdf_text", "text": t, "raw": t}
                  for n, t in PAGES.items()]}))
    pk = tmp_path / ".cache" / "packets" / "ngmdb_5"
    pk.mkdir(parents=True)
    (pk / "index.json").write_text(json.dumps(INDEX))
    kw = dict(text_dir=text, packets_dir=tmp_path / ".cache" / "packets", out_dir=tmp_path / "data" / "extracted",
              review_dir=tmp_path / "data" / "review", done_dir=tmp_path / ".checkpoints" / "extract",
              catalog={"ngmdb:5": RECORD}, lexicon=Lexicon([]))

    def run(res, name):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(res))
        return ingest.ingest([p], **kw)

    def out():
        return json.loads((kw["out_dir"] / "ngmdb_5.json").read_text())
    return run, out, kw


def _names(doc):
    return [u["name"]["value"] for u in doc["units"]]


def test_partial_then_complete(env):
    run, out, kw = env
    s = run(result(["packet-01"], [WANDO, LADSON]), "p1")
    doc = out()
    assert doc["complete"] is False and doc["blocks_done"] == ["1", "2"]
    assert s["complete"] is False
    assert not (kw["done_dir"] / "ngmdb_5.json").exists()

    run(result(["packet-02"], [ASHLEY], [AH1]), "p2")
    doc = out()
    assert doc["complete"] is True and doc["blocks_done"] == ["1", "2", "3", "4"]
    assert _names(doc) == ["Wando Formation", "Ladson Formation", "Ashley Formation"]  # earlier values survive
    assert doc["observations"][0]["label"]["value"] == "AH-1"
    assert doc["packets"] == ["packet-01", "packet-02"]
    assert (kw["done_dir"] / "ngmdb_5.json").exists()


def test_reingesting_a_packet_replaces_only_its_pages(env):
    run, out, _ = env
    run(result(["packet-01"], [WANDO, LADSON]), "p1")
    run(result(["packet-02"], [ASHLEY], [AH1]), "p2")
    run(result(["packet-01"], [WANDO]), "p1-again")  # Ladson dropped on the re-read
    doc = out()
    assert _names(doc) == ["Ashley Formation", "Wando Formation"]  # Ladson (page 2) re-read away; no duplicate
    assert doc["observations"][0]["label"]["value"] == "AH-1"
    assert doc["complete"] is True


def test_duplicate_values_across_packets_are_dropped(env):
    run, out, _ = env
    run(result(["packet-01"], [WANDO]), "p1")
    # The second packet's reader also recorded Wando (citing page 1) plus a new value.
    run(result(["packet-02"], [WANDO, ASHLEY]), "p2")
    doc = out()
    assert _names(doc) == ["Wando Formation", "Ashley Formation"]


def test_review_items_kept_for_other_packets(env):
    run, _, kw = env
    bad1 = {"name": v("Penholoway Formation", 2, "Penholoway Formation is gravel")}
    bad2 = {"name": v("Edisto Formation", 4, "Edisto Formation is limestone")}
    run(result(["packet-01"], [bad1]), "p1")
    run(result(["packet-02"], [bad2]), "p2")
    items = json.loads((kw["review_dir"] / "queue.json").read_text())["items"]
    assert {i["page"] for i in items} == {2, 4}
    run(result(["packet-02"], [ASHLEY]), "p2-fixed")
    items = json.loads((kw["review_dir"] / "queue.json").read_text())["items"]
    assert {i["page"] for i in items} == {2}


def test_unknown_packet_is_refused(env):
    run, _, _ = env
    with pytest.raises(ingest.IngestError, match="packet-09"):
        run(result(["packet-09"], [WANDO]), "bad")


def test_result_without_packets_covers_the_whole_document(env):
    run, out, _ = env
    r = result([], [WANDO, ASHLEY])
    del r["packets"]
    run(r, "whole")
    assert out()["complete"] is True


def test_missing_packet_index_needs_next_batch(env, tmp_path):
    run, _, kw = env
    (kw["packets_dir"] / "ngmdb_5" / "index.json").unlink()
    with pytest.raises(ingest.IngestError, match="next_batch"):
        run(result(["packet-01"], [WANDO]), "p1")
