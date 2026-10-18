"""Image packets: page renders and overlapping tiles from the cached PDF, with a manifest of boxes."""

import json
import shutil
import struct

import pytest

from extract import images
from tests.pdfgen import make_pdf

SID = "ngmdb:7"
POPPLER = shutil.which("pdftoppm") and shutil.which("pdfinfo")
needs_poppler = pytest.mark.skipif(not POPPLER, reason="poppler-utils not installed")


def _png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", head[16:24])


@pytest.fixture
def cache(tmp_path):
    cache = tmp_path / ".cache"
    (cache / "text").mkdir(parents=True)
    pdf = cache / "pdfs" / "ngmdb_7" / "01.pdf"
    pdf.parent.mkdir(parents=True)
    make_pdf(pdf, [["A-A' cross section", "Vertical exaggeration 20x"], []])
    (cache / "text" / "ngmdb_7.json").write_text(json.dumps({"source_id": SID, "files": [
        {"url": "https://ngmdb.usgs.gov/img2/x/7_1", "path": str(pdf), "via": "ngmdb_image", "pages": 2,
         "first_page": 1}],
        "pages": [{"page": 1, "file": 0, "file_page": 1, "method": "ocr", "text": "A-A' cross section"},
                  {"page": 2, "file": 0, "file_page": 2, "method": "none", "text": ""}]}))
    return cache


def fake_renderer(calls):
    """Writes a tiny file per tile instead of running pdftoppm; records each call."""
    def run(pdf, file_page, dpi, box, out):
        calls.append((file_page, dpi, tuple(box)))
        out.write_bytes(b"png")
    return run


SIZER = lambda pdf, n: (612.0, 792.0)


# --- the grid ------------------------------------------------------------------------------

def test_grid_covers_the_page_with_overlap_and_tiles_no_larger_than_the_limit():
    tiles = images.plan_grid(4200, 5400, max_tile_px=1500, overlap_px=120)
    cols = {t["col"] for t in tiles}
    rows = {t["row"] for t in tiles}
    assert len(tiles) == len(cols) * len(rows) == 12  # 3 columns x 4 rows
    for t in tiles:
        x0, y0, x1, y1 = t["px_box"]
        assert x1 - x0 <= 1500 and y1 - y0 <= 1500
        assert 0 <= x0 < x1 <= 4200 and 0 <= y0 < y1 <= 5400
    # neighbours overlap by at least the overlap
    row1 = sorted((t for t in tiles if t["row"] == 1), key=lambda t: t["col"])
    for a, b in zip(row1, row1[1:]):
        assert a["px_box"][2] - b["px_box"][0] >= 120
    assert max(t["px_box"][2] for t in tiles) == 4200 and max(t["px_box"][3] for t in tiles) == 5400
    assert min(t["px_box"][0] for t in tiles) == 0 and min(t["px_box"][1] for t in tiles) == 0


def test_explicit_grid_is_columns_by_rows():
    tiles = images.plan_grid(3000, 2000, cols=3, rows=2, overlap_px=100)
    assert len(tiles) == 6 and {t["col"] for t in tiles} == {1, 2, 3} and {t["row"] for t in tiles} == {1, 2}
    assert images.parse_grid("3x2") == (3, 2)
    with pytest.raises(images.ImagesError):
        images.parse_grid("3by2")


def test_small_page_is_one_tile():
    assert [t["px_box"] for t in images.plan_grid(800, 600, max_tile_px=1500, overlap_px=120)] == [[0, 0, 800, 600]]


# --- rendering ------------------------------------------------------------------------------

def test_render_writes_tiles_and_a_manifest_with_pixel_and_point_boxes(cache):
    calls = []
    m = images.render(SID, [1], dpi=100, grid=(2, 2), cache_dir=cache, renderer=fake_renderer(calls),
                      sizer=SIZER, native=lambda pdf, n: None)
    d = cache / "images" / "ngmdb_7"
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["source_id"] == SID and manifest == images.load_manifest(SID, cache / "images")
    tiles = [t for t in m["tiles"] if t["kind"] == "tile"]
    assert len(tiles) == 4
    for t in tiles:
        assert (d / t["file"]).exists() and t["page"] == 1 and t["file_page"] == 1 and t["dpi"] == 100
        # points = pixels * 72 / dpi, from the page's top-left corner
        assert t["pt_box"] == [round(v * 72 / 100, 2) for v in t["px_box"]]
        assert t["size_px"] == [t["px_box"][2] - t["px_box"][0], t["px_box"][3] - t["px_box"][1]]
        assert t["tile"] in manifest["tiles"]
        assert t["estimated_tokens"] > 0
    assert manifest["pages"]["1"]["size_pt"] == [612.0, 792.0]
    assert manifest["pages"]["1"]["size_px"] == [850, 1100]  # at 100 dpi
    # an overview of the whole page comes first, for finding the cross sections and the legend
    overview = [t for t in m["tiles"] if t["kind"] == "overview"]
    assert len(overview) == 1 and overview[0]["pt_box"] == [0, 0, 612.0, 792.0]
    assert manifest["files"]["0"]["sha256"] and manifest["files"]["0"]["url"] == "https://ngmdb.usgs.gov/img2/x/7_1"
    assert all(t["file_index"] == 0 for t in tiles)
    assert all(c[0] == 1 for c in calls)


def test_render_is_resumable_and_never_renders_a_tile_twice(cache):
    calls = []
    kw = dict(dpi=100, grid=(2, 2), cache_dir=cache, renderer=fake_renderer(calls), sizer=SIZER,
              native=lambda pdf, n: None)
    images.render(SID, [1], **kw)
    n = len(calls)
    again = images.render(SID, [1], **kw)
    assert len(calls) == n and len([t for t in again["tiles"] if t["kind"] == "tile"]) == 4
    # a different request adds tiles to the same manifest
    images.render(SID, [1], dpi=100, crop=(0, 396, 612, 792), **{k: v for k, v in kw.items() if k != "dpi" and k != "grid"})
    manifest = images.load_manifest(SID, cache / "images")
    crops = [t for t in manifest["tiles"].values() if t["kind"] == "crop"]
    assert crops and all(t["pt_box"][1] >= 396 for t in crops)
    assert len([t for t in manifest["tiles"].values() if t["kind"] == "tile"]) == 4


def test_render_does_not_go_above_the_scan_resolution(cache):
    m = images.render(SID, [1], dpi=300, cache_dir=cache, renderer=fake_renderer([]), sizer=SIZER,
                      native=lambda pdf, n: 144)
    tile = next(t for t in m["tiles"] if t["kind"] == "tile")
    assert tile["dpi"] == 144
    assert m["pages"]["1"]["native_ppi"] == 144 and m["pages"]["1"]["dpi_requested"] == 300


def test_render_never_downloads(cache, monkeypatch):
    (cache / "pdfs" / "ngmdb_7" / "01.pdf").unlink()
    import harvest.pdfs as hp
    monkeypatch.setattr(hp, "process", lambda *a, **k: pytest.fail("downloaded"))
    with pytest.raises(images.ImagesError, match=r"python -m harvest.pdfs --id ngmdb:7"):
        images.render(SID, [1], cache_dir=cache, renderer=fake_renderer([]), sizer=SIZER)
    (cache / "text" / "ngmdb_7.json").unlink()
    with pytest.raises(images.ImagesError, match=r"python -m harvest.pdfs --id ngmdb:7"):
        images.render(SID, [1], cache_dir=cache, renderer=fake_renderer([]), sizer=SIZER)


def test_render_refuses_unknown_pages(cache):
    with pytest.raises(images.ImagesError, match="no page 9"):
        images.render(SID, [9], cache_dir=cache, renderer=fake_renderer([]), sizer=SIZER)


@needs_poppler
def test_render_with_pdftoppm_makes_pngs_of_the_manifest_size(cache):
    m = images.render(SID, [1], dpi=72, grid=(2, 1), cache_dir=cache)
    d = cache / "images" / "ngmdb_7"
    for t in m["tiles"]:
        w, h = _png_size(d / t["file"])
        assert abs(w - t["size_px"][0]) <= 1 and abs(h - t["size_px"][1]) <= 1
    assert m["pages"]["1"]["size_pt"] == [612.0, 792.0]


# --- locators ---------------------------------------------------------------------------------

def test_resolve_turns_a_tile_box_into_page_pixels_and_pdf_points(cache):
    images.render(SID, [1], dpi=100, grid=(2, 2), cache_dir=cache, renderer=fake_renderer([]), sizer=SIZER,
                  native=lambda pdf, n: None)
    manifest = images.load_manifest(SID, cache / "images")
    tile = next(t for t in manifest["tiles"].values() if t["kind"] == "tile" and t["row"] == 2 and t["col"] == 2)
    r = images.resolve(manifest, tile["tile"], [10, 20, 110, 70])
    x0, y0 = tile["px_box"][:2]
    assert r["page"] == 1 and r["page_px_box"] == [x0 + 10, y0 + 20, x0 + 110, y0 + 70]
    assert r["pt_box"] == [round(v * 72 / 100, 2) for v in r["page_px_box"]]
    loc = images.locator("https://ngmdb.usgs.gov/img2/x/7_1", r)
    left, top, right, bottom = r["pt_box"]
    assert loc == (f"https://ngmdb.usgs.gov/img2/x/7_1#page=1&viewrect={left:g},{top:g},"
                   f"{round(right - left, 2):g},{round(bottom - top, 2):g}")
    with pytest.raises(images.ImagesError, match="not in the image manifest"):
        images.resolve(manifest, "p1-100dpi-r9c9", [0, 0, 1, 1])
    with pytest.raises(images.ImagesError, match="outside"):
        images.resolve(manifest, tile["tile"], [0, 0, 99999, 10])
    with pytest.raises(images.ImagesError, match="empty"):
        images.resolve(manifest, tile["tile"], [10, 10, 10, 30])


def test_image_confidence_is_capped_below_text_checked_values():
    cfg = images.CONFIG
    c = cfg["images"]["confidence"]
    best = images.confidence(0.95, "agree", False, False, cfg)
    assert best == c["max"] < 0.95 * 0.9  # below an OCR-text value from the same map, verified
    assert images.confidence(0.95, "unclear", False, False, cfg) < best
    assert images.confidence(0.95, "agree", True, False, cfg) < best
    assert images.confidence(0.95, "agree", False, True, cfg) < best
    low_cap = json.loads(json.dumps(cfg))
    low_cap["images"]["confidence"]["max"] = 0.3
    assert images.confidence(0.95, "agree", False, False, low_cap) == 0.3


# --- the command ---------------------------------------------------------------------------

def test_cli_prints_the_manifest_and_tiles(cache, monkeypatch, capsys):
    monkeypatch.setattr(images, "CACHE", cache)
    monkeypatch.setattr(images, "_pdftoppm", fake_renderer([]))
    monkeypatch.setattr(images, "page_size", SIZER)
    monkeypatch.setattr(images, "_native_ppi", lambda pdf, n: None)
    assert images.main([SID, "--pages", "1", "--dpi", "100", "--grid", "2x2"]) == 0
    out = capsys.readouterr().out
    assert "manifest:" in out and "view:" in out and "p1-100dpi-2x2-r2c2" in out
    assert images.main(["ngmdb:404", "--pages", "1"]) == 1
