import json
import random

import pytest

from extract import next_batch, prep, reading_list as rl

CATALOG = json.loads((rl.ROOT / "data" / "catalog" / "sc_catalog.json").read_text())
BY_ID = {r["id"]: r for r in CATALOG}


@pytest.fixture(scope="module")
def ctx():
    return rl.Context.load()


def rec(rid="test:1", title="Geologic map of a place", bbox=None, kind="map", scale=24000, themes=("bedrock",),
        keywords=("geologic map", "geology"), quads=(), series="", series_key=None,
        publisher="U.S. Geological Survey", online=True, year=2000):
    return {"id": rid, "title": title, "authors": "A", "year": year, "publisher": publisher, "series": series,
            "series_key": series_key, "scale": scale, "themes": list(themes), "quadrangles": list(quads),
            "bbox": bbox, "citation": f"C {rid}", "keywords": list(keywords), "kind": kind, "status": "published",
            "availability": {"online": online, "pdf": [], "doi": None, "scgs_ftp": [], "gems_download": None}}


# --- geometry ----------------------------------------------------------------

def test_share_inside_and_outside_sc(ctx):
    assert rl.sc_share([-81.2, 33.9, -81.0, 34.1], ctx) == pytest.approx(1.0)   # Columbia
    assert rl.sc_share([-84.0, 39.5, -83.0, 40.5], ctx) == 0.0                   # Ohio
    half = rl.sc_share([-83.0, 34.8, -82.6, 35.6], ctx)                           # straddles the NC line
    assert 0.1 < half < 0.7


def test_share_ignores_open_ocean_on_the_sc_coast(ctx):
    # Capers Inlet quadrangle: about half sea, but all of its land is South Carolina
    assert rl.sc_share([-79.75, 32.75, -79.625, 32.875], ctx) > 0.9


def test_share_of_national_and_antimeridian_boxes_is_tiny(ctx):
    assert rl.sc_share([-125.0, 24.0, -66.0, 50.0], ctx) < 0.02
    assert rl.sc_share([177.0, 18.9, -67.0, 71.4], ctx) < 0.02  # crosses the antimeridian
    assert rl.sc_share(None, ctx) is None


# --- scorer ------------------------------------------------------------------

def test_sc_quadrangle_map_is_included_with_reasons(ctx):
    s = rl.score(rec(title="Geologic map of the Example quadrangle, South Carolina", bbox=[-81.25, 33.625, -81.125, 33.75],
                     quads=["EXAMPLE"], publisher="South Carolina Geological Survey", series_key="SCGS GQM-1"), ctx)
    assert s["include"] and s["score"] >= rl.THRESHOLD + 30
    text = "; ".join(s["reasons"])
    assert "inside SC" in text and "quadrangle" in text and "SCGS" in text


def test_national_compilation_is_excluded(ctx):
    s = rl.score(rec(title="Geologic map of the conterminous United States", bbox=[-125.0, 24.0, -66.0, 50.0],
                     scale=2500000), ctx)
    assert not s["include"]
    assert any("national" in r for r in s["reasons"])


def test_water_quality_only_report_is_excluded_even_inside_sc(ctx):
    s = rl.score(rec(title="Nutrient and pesticide concentrations in streams of the Example basin, South Carolina",
                     kind="publication", scale=None, themes=(), bbox=[-81.2, 33.9, -81.0, 34.1],
                     series_key="USGS SIR-2001-1"), ctx)
    assert not s["include"]
    assert any("not geologic" in r for r in s["reasons"])


def test_hydrogeology_is_geology(ctx):
    s = rl.score(rec(title="Hydrogeologic framework of the Example area, South Carolina", kind="publication",
                     scale=None, themes=(), bbox=[-81.2, 33.9, -81.0, 34.1], series_key="USGS WRIR-90-1"), ctx)
    assert s["include"]


def test_pilot_records_come_first(ctx):
    pilot = rec("test:p", title="Water levels in wells, Charleston County, South Carolina", kind="publication",
                themes=(), scale=None, bbox=[-80.1, 32.7, -79.9, 32.9])
    strong = rec("test:s", title="Geologic map of the Example quadrangle, South Carolina", bbox=[-81.25, 33.625, -81.125, 33.75],
                 quads=["EXAMPLE"], publisher="South Carolina Geological Survey", series_key="SCGS GQM-1")
    out = rl.build([strong, pilot], ctx)
    assert out["ids"] == ["test:p", "test:s"]
    assert out["scores"]["test:p"]["pilot"] is True and out["scores"]["test:s"]["pilot"] is False


@pytest.mark.parametrize("rid", ["ngmdb:117526", "ngmdb:92641", "ngmdb:5629", "ngmdb:111893", "ngmdb:42961",
                                 "ngmdb:24077", "ngmdb:98103", "ngmdb:13226"])
def test_catalog_examples_included(ctx, rid):
    s = rl.score(BY_ID[rid], ctx)
    assert s["include"], (rid, s)


@pytest.mark.parametrize("rid", ["ngmdb:114301", "ngmdb:118515", "ngmdb:105281", "ngmdb:71847", "ngmdb:118087",
                                 "ngmdb:110819"])
def test_catalog_examples_excluded(ctx, rid):
    s = rl.score(BY_ID[rid], ctx)
    assert not s["include"], (rid, s)
    assert s["reasons"]


# --- builder -----------------------------------------------------------------

def test_build_is_deterministic_and_lists_every_exclusion(ctx):
    a = rl.build(CATALOG, ctx)
    shuffled = CATALOG[:]
    random.Random(7).shuffle(shuffled)
    b = rl.build(shuffled, ctx)
    assert a == b
    assert set(a["ids"]) | set(a["excluded"]) == set(BY_ID)
    offline = next(r["id"] for r in CATALOG if not r["availability"].get("online"))
    assert "no open full text" in a["excluded"][offline]
    assert not set(a["ids"]) & set(a["excluded"])
    assert all(a["excluded"][i] for i in a["excluded"])  # every exclusion has a reason
    assert len(a["ids"]) == len(set(a["ids"]))


def test_merged_gis_sources_are_excluded_with_reason(ctx):
    merged = sorted(ctx.merged)[0]
    out = rl.build(CATALOG, ctx)
    assert merged not in out["ids"]
    assert "merged" in out["excluded"][merged]


def test_committed_files_match_the_builder(ctx):
    out = rl.build(CATALOG, ctx)
    listed = json.loads(rl.LIST_PATH.read_text())
    scores = json.loads(rl.SCORES_PATH.read_text())
    assert listed["ids"] == out["ids"] and listed["about"]
    online = {i for i, r in BY_ID.items() if r["availability"].get("online")}
    assert {e["id"] for e in scores["records"]} == online
    assert set(scores["no_open_full_text"]["ids"]) == set(BY_ID) - online
    assert len(rl.SCORES_PATH.read_text()) < 400_000


def test_written_list_works_with_prep_and_next_batch(ctx, tmp_path):
    out = rl.build(CATALOG, ctx)
    list_path, scores_path = tmp_path / "reading_list.json", tmp_path / "scores.json"
    rl.write(out, list_path, scores_path)
    first = out["ids"][0]
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / f"{next_batch.packets.safe_id(first)}.json").write_text(json.dumps({"complete": True}))
    todo = prep.todo(list_path, extracted, tmp_path / "review")
    assert todo == out["ids"][1:]
    queued = {r["id"] for r in next_batch.pdfs.queue(CATALOG)}
    assert set(out["ids"]) <= queued  # next_batch --id can hand out every listed record
    scores = json.loads(scores_path.read_text())
    entry = next(e for e in scores["records"] if e["id"] == first)
    assert entry["rank"] == 1 and entry["included"] and entry["reasons"]
