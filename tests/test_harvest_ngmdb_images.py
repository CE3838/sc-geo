"""NGMDB browse images (Zoomify tiles) as a full-text source: tiles -> one-page PDF -> OCR."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from extract import pdftext
from harvest import ngmdb_images as ni
from harvest import pdfs
from tests.pdfgen import make_pdf

POPPLER = shutil.which("pdftoppm") and shutil.which("pdfinfo")
needs_poppler = pytest.mark.skipif(not POPPLER, reason="poppler-utils not installed")


def test_tiers_match_ngmdb_numtiles():
    tiers = ni.tiers(8400, 10800, 256)
    assert tiers[-1] == (33, 43) and tiers[0] == (1, 1)
    assert sum(c * r for c, r in tiers) == 1936  # NUMTILES in ImageProperties.xml


def test_tile_urls_use_tile_groups():
    base = "https://ngmdb.usgs.gov/img2/100000_100999/100343_1"
    assert ni.tile_url(base, 8400, 10800, 0, 0, 0) == base + "/TileGroup0/0-0-0.jpg"
    # First tile of the full-resolution tier is tile 517 -> group 2.
    assert ni.tile_url(base, 8400, 10800, 6, 0, 0) == base + "/TileGroup2/6-0-0.jpg"
    assert ni.tile_size(8400, 10800, 6, 32, 42) == (8400 - 32 * 256, 10800 - 42 * 256)


def test_image_properties():
    xml = '<IMAGE_PROPERTIES WIDTH="8400" HEIGHT="10800" NUMTILES="1936" NUMIMAGES="1" VERSION="1.8" TILESIZE="256" />'
    assert ni.image_properties(xml) == {"width": 8400, "height": 10800, "tile_size": 256, "num_tiles": 1936}


def jpeg(tmp_path, w, h, lines=("x",), name="t"):
    """A w x h JPEG made with pdftoppm (no imaging library needed)."""
    pdf = make_pdf(tmp_path / f"{name}.pdf", [list(lines)])
    out = tmp_path / name
    subprocess.run(["pdftoppm", "-jpeg", "-singlefile", "-scale-to-x", str(w), "-scale-to-y", str(h),
                    str(pdf), str(out)], check=True)
    return (tmp_path / f"{name}.jpg").read_bytes()


@needs_poppler
def test_jpeg_size(tmp_path):
    assert ni.jpeg_size(jpeg(tmp_path, 44, 30)) == (44, 30, 3)


class TileFetcher:
    def __init__(self, base, props, tiles):
        self.base, self.props, self.tiles, self.calls = base, props, tiles, []

    def text(self, url):
        self.calls.append(url)
        assert url == self.base + "/ImageProperties.xml"
        return self.props

    def bytes(self, url):
        self.calls.append(url)
        return self.tiles(url)


@needs_poppler
def test_build_tiled_pdf_is_one_page_of_the_full_image(tmp_path):
    base = "https://ngmdb.usgs.gov/img2/1_1/1_1"
    props = '<IMAGE_PROPERTIES WIDTH="300" HEIGHT="200" NUMTILES="3" TILESIZE="256" />'
    sizes = {"1-0-0.jpg": (256, 200), "1-1-0.jpg": (44, 200)}
    f = TileFetcher(base, props, lambda u: jpeg(tmp_path, *sizes[u.rsplit("/", 1)[1]], name=u.rsplit("/", 1)[1][:-4]))
    dest = ni.build_pdf(base, tmp_path / "img.pdf", f)
    info = subprocess.run(["pdfinfo", str(dest)], capture_output=True, text=True).stdout
    assert re.search(r"Pages:\s+1\n", info)
    assert "150 x 100 pts" in info  # 0.5 pt per pixel: 300 x 200 px
    assert sorted(u.rsplit("/", 2)[1] + "/" + u.rsplit("/", 1)[1] for u in f.calls[1:]) == [
        "TileGroup0/1-0-0.jpg", "TileGroup0/1-1-0.jpg"]
    assert subprocess.run(["pdftoppm", "-r", "36", "-png", str(dest), str(tmp_path / "r")]).returncode == 0
    assert pdftext.extract(dest, ocr=None)[0]["method"] == "none"  # an image: OCR needed


@needs_poppler
def test_ocr_renders_at_the_images_native_resolution(tmp_path):
    base = "https://ngmdb.usgs.gov/img2/1_1/1_1"
    props = '<IMAGE_PROPERTIES WIDTH="300" HEIGHT="200" TILESIZE="256" />'
    sizes = {"1-0-0.jpg": (256, 200), "1-1-0.jpg": (44, 200)}
    f = TileFetcher(base, props, lambda u: jpeg(tmp_path, *sizes[u.rsplit("/", 1)[1]], name=u.rsplit("/", 1)[1][:-4]))
    dest = ni.build_pdf(base, tmp_path / "img.pdf", f)
    assert pdftext.native_dpi(dest, 1) == 144  # tiles are placed at 0.5 pt per pixel
    text_pdf = make_pdf(tmp_path / "t.pdf", [["no images here"]])
    assert pdftext.native_dpi(text_pdf, 1) is None


@pytest.mark.skipif(not POPPLER or not shutil.which("tesseract"), reason="needs poppler and tesseract (CI)")
def test_tiled_image_is_ocred(tmp_path):
    page = make_pdf(tmp_path / "map.pdf", [["WANDO FORMATION CLAYEY SAND", "LADSON FORMATION"]])
    # Render at 200 dpi (1700 x 2200 px) and cut into 256-px tiles with pdftoppm's crop box.
    base = "https://ngmdb.usgs.gov/img2/9_9/9_9"
    w, h = 1700, 2200
    props = f'<IMAGE_PROPERTIES WIDTH="{w}" HEIGHT="{h}" TILESIZE="256" />'
    top = len(ni.tiers(w, h, 256)) - 1

    def tile(url):
        z, x, y = map(int, url.rsplit("/", 1)[1][:-4].split("-"))
        assert z == top
        tw, th = ni.tile_size(w, h, z, x, y)
        out = tmp_path / f"t{x}_{y}"
        subprocess.run(["pdftoppm", "-jpeg", "-r", "200", "-x", str(x * 256), "-y", str(y * 256), "-W", str(tw),
                        "-H", str(th), "-singlefile", str(page), str(out)], check=True)
        return Path(str(out) + ".jpg").read_bytes()

    dest = ni.build_pdf(base, tmp_path / "img.pdf", TileFetcher(base, props, tile))
    pages = pdftext.extract(dest, ocr="auto")
    assert pages[0]["method"] == "ocr"
    assert "WANDO" in pages[0]["text"].upper()


# --- resolving and running -----------------------------------------------------

HOLDINGS = """<script type="text/javascript">var holdings = {"publication":100343,"images":[
{"w":8400,"img":"/img2/100000_100999/100343_1","h":10800,"provider":"South Carolina Geological Survey",
 "downloads":[],"item":52238},
{"w":900,"img":"/img2/100000_100999/100343_2","h":700,"provider":"Some Journal","downloads":[],"item":52239}]}
</script>"""


def test_resolve_offers_browse_images_from_allowed_providers_only():
    rec = {"id": "ngmdb:100343", "title": "Geologic Map of the Rockville Quadrangle", "publisher":
           "South Carolina Geological Survey", "kind": "map", "availability": {"pdf": [], "doi": None, "scgs_ftp": []},
           "ngmdb_url": "https://ngmdb.usgs.gov/Prodesc/proddesc_100343.htm"}

    class F:
        def text(self, url):
            return HOLDINGS

        def json(self, url):  # Crossref: no SCGS maps there
            return {"message": {"items": []}}

    r = pdfs.resolve(rec, F(), email=None)
    assert r["candidates"] == [{"url": "https://ngmdb.usgs.gov/img2/100000_100999/100343_1", "via": "ngmdb_image"}]
    assert ni.browse_images(HOLDINGS, ["South Carolina Geological Survey"]) == [
        "https://ngmdb.usgs.gov/img2/100000_100999/100343_1"]


def test_images_only_for_records_published_by_allowed_publishers():
    """A USGS-supplied scan of an AAPG map is still AAPG's map."""
    rec = {"id": "ngmdb:9", "title": "Some AAPG map", "publisher": "American Association of Petroleum Geologists",
           "kind": "map", "availability": {"pdf": [], "doi": None, "scgs_ftp": []},
           "ngmdb_url": "https://ngmdb.usgs.gov/Prodesc/proddesc_9.htm"}

    class F:
        def text(self, url):
            return HOLDINGS.replace("South Carolina Geological Survey", "U.S. Geological Survey")

        def json(self, url):
            return {"message": {"items": []}}

    assert pdfs.resolve(rec, F(), email=None)["candidates"] == []


def test_images_are_only_a_fallback():
    with_scan = HOLDINGS.replace('"downloads":[],"item":52238', '"downloads":[{"fmt":2}],"item":52238')
    assert ni.browse_images(with_scan, ["South Carolina Geological Survey"]) == []  # the PDF scan is used instead


@needs_poppler
def test_run_moves_image_records_out_of_needs_access(tmp_path):
    rec = {"id": "ngmdb:100343", "title": "Rockville", "authors": "A", "year": 2006, "publisher":
           "South Carolina Geological Survey", "series": "OFR-202", "series_key": None, "scale": 24000, "themes": [],
           "quadrangles": [], "bbox": [-80.25, 32.5, -80.125, 32.625], "citation": "C", "keywords": [],
           "availability": {"online": True, "gis": False, "gems_download": None, "gis_download": None, "pdf": [],
                            "doi": None, "scgs_ftp": []},
           "ngmdb_url": "https://ngmdb.usgs.gov/Prodesc/proddesc_100343.htm", "kind": "map", "status": "published"}
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps([rec]))
    base = "https://ngmdb.usgs.gov/img2/100000_100999/100343_1"
    tile = jpeg(tmp_path, 100, 80)

    class F:
        calls = []

        def text(self, url):
            self.calls.append(url)
            if url.endswith("ImageProperties.xml"):
                return '<IMAGE_PROPERTIES WIDTH="100" HEIGHT="80" TILESIZE="256" />'
            return HOLDINGS

        def json(self, url):
            return {"records": []}

        def bytes(self, url):
            self.calls.append(url)
            return tile

    review = tmp_path / "data" / "review"
    review.mkdir(parents=True)
    (review / "needs_access.json").write_text(json.dumps({"records": [{"id": "ngmdb:100343", "title": "Rockville"}]}))
    status = pdfs.run(catalog_path=cat, checkpoint_dir=tmp_path / "ck", cache_dir=tmp_path / ".cache",
                      review_dir=review, fetcher=F(), ocr=None, log=lambda *a: None, workers=1)
    assert status["by_status"] == {"needs_ocr": 1}  # read once OCR is available; no longer needs access
    assert json.loads((review / "needs_access.json").read_text())["records"] == []
    ck = json.loads((tmp_path / "ck" / "ngmdb_100343.json").read_text())
    assert ck["files"][0]["via"] == "ngmdb_image" and ck["files"][0]["url"] == base
    assert not list((tmp_path / "data").rglob("*.pdf")) and not list((tmp_path / "data").rglob("*.jpg"))
