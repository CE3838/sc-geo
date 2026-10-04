import json
import shutil
from pathlib import Path

import pytest

from harvest import pdfs
from tests.pdfgen import make_pdf

PILOT = [-80.47, 32.48, -79.30, 33.22]
EMAIL = "someone@example.org"


def rec(rid, bbox, kind="publication", publisher="U.S. Geological Survey", year=2000, **av):
    availability = {"online": True, "gis": False, "gems_download": None, "gis_download": None, "pdf": [],
                    "doi": None, "scgs_ftp": []}
    availability.update(av)
    return {"id": rid, "title": f"Title {rid}", "authors": "Weems, R.E.", "year": year, "publisher": publisher,
            "series": "Open-File Report", "series_key": None, "scale": 24000, "themes": [], "quadrangles": [],
            "bbox": bbox, "citation": f"Citation for {rid}", "keywords": [], "availability": availability,
            "ngmdb_url": f"https://ngmdb.usgs.gov/Prodesc/proddesc_{rid.split(':')[1]}.htm", "kind": kind,
            "status": "published", "provenance": []}


CHS = rec("ngmdb:1", [-80.0, 32.75, -79.75, 33.0], kind="map")
CHS_BIG = rec("ngmdb:2", [-81.0, 32.0, -79.0, 34.0])  # regional; ordered after the quadrangle map
STATE = rec("ngmdb:3", [-83.4, 32.0, -78.5, 35.2])  # statewide
COASTAL = rec("ngmdb:4", [-81.5, 33.2, -81.25, 33.4])  # Coastal Plain, not Charleston
PIEDMONT = rec("ngmdb:5", [-82.5, 34.75, -82.25, 35.0])
MERGED = rec("ngmdb:6", [-80.0, 32.75, -79.75, 33.0], gems_download="https://x/gems.zip")


def test_queue_order_and_merged_excluded():
    q = pdfs.queue([PIEDMONT, STATE, COASTAL, MERGED, CHS_BIG, CHS], PILOT)
    ids = [r["id"] for r in q]
    assert "ngmdb:6" not in ids
    assert ids[0] == "ngmdb:1"
    assert ids.index("ngmdb:4") < ids.index("ngmdb:5")
    tiers = {r["id"]: r["_tier"] for r in q}
    assert tiers["ngmdb:1"] == 0 and tiers["ngmdb:4"] == 1 and tiers["ngmdb:5"] == 2
    assert tiers["ngmdb:3"] != 0  # statewide map is not 'about' Charleston


def test_geology_first_within_a_tier():
    stormwater = {**rec("ngmdb:30", [-80.0, 32.80, -79.99, 32.81]), "title": "Characterization of stormwater"}
    geomap = {**rec("ngmdb:31", [-80.0, 32.75, -79.75, 33.0]), "title": "Geologic map of the Ladson quadrangle"}
    themed = {**rec("ngmdb:32", [-80.0, 32.75, -79.70, 33.0]), "title": "Something", "themes": ["surficial"]}
    ids = [r["id"] for r in pdfs.queue([stormwater, geomap, themed], PILOT)]
    assert ids == ["ngmdb:31", "ngmdb:32", "ngmdb:30"]


def test_coastal_plain_test():
    assert pdfs.in_coastal_plain([-80.0, 32.7, -79.9, 32.8])
    assert not pdfs.in_coastal_plain([-82.5, 34.75, -82.25, 35.0])


# --- resolving ----------------------------------------------------------------

NGMDB_PAGE = """<html><a href="/ngm-bin/count_pub_refs.pl?publisher=USGS&amp;url=https%3A%2F%2Fpubs.usgs.gov%2Fpublication%2Fb1537C&amp;ref_type=p">pubs</a>
<script type="text/javascript">var holdings = {"publication":1,"images":[{"item":18044,"downloads":[{"fmt":5},{"fmt":2},{"fmt":3}]},
{"item":18045,"downloads":[{"fmt":3}]},{"item":18046,"downloads":[]}]}</script></html>"""
PUBS_B1537C = {"indexId": "b1537C", "links": [
    {"type": {"text": "Document"}, "url": "https://pubs.usgs.gov/bul/1537c/report.pdf"},
    {"type": {"text": "Thumbnail"}, "url": "https://pubs.usgs.gov/bul/1537c/thumb.jpg"}]}


class FakeFetcher:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _get(self, url):
        self.calls.append(url)
        for key, val in self.routes.items():
            if url.startswith(key):
                if isinstance(val, Exception):
                    raise val
                return val
        raise OSError("HTTP Error 404: Not Found")

    def text(self, url):
        return self._get(url)

    def json(self, url):
        return self._get(url)

    def download(self, url, dest):
        data = self._get(url)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(data)
        return Path(dest)


def test_ngmdb_holdings_scans():
    urls = pdfs.ngmdb_scans(NGMDB_PAGE, [2, 3])
    assert urls == ["https://ngmdb.usgs.gov/ngm-bin/pdp/download.pl?q=18044_1_2",
                    "https://ngmdb.usgs.gov/ngm-bin/pdp/download.pl?q=18045_1_3"]


def test_publisher_links_from_ngmdb_page():
    assert pdfs.publisher_links(NGMDB_PAGE) == ["https://pubs.usgs.gov/publication/b1537C"]


def test_resolve_prefers_text_reports_over_scans():
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": NGMDB_PAGE,
                     "https://pubs.usgs.gov/pubs-services/publication/b1537C": PUBS_B1537C})
    r = pdfs.resolve({**CHS, "kind": "publication"}, f, email=None)
    assert [c["url"] for c in r["candidates"]] == ["https://pubs.usgs.gov/bul/1537c/report.pdf"]
    assert r["candidates"][0]["via"] == "pubs_usgs"


def test_map_without_pubs_plates_also_gets_scans():
    gq = rec("ngmdb:528", CHS["bbox"], kind="map")
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": NGMDB_PAGE,
                     "https://pubs.usgs.gov/pubs-services/publication/b1537C": PUBS_B1537C})
    r = pdfs.resolve(gq, f, email=None)
    assert [c["via"] for c in r["candidates"]] == ["pubs_usgs", "ngmdb_scan", "ngmdb_scan"]
    plates = {"indexId": "b1537C", "links": PUBS_B1537C["links"] + [
        {"type": {"text": "Plate"}, "url": "https://pubs.usgs.gov/bul/1537c/plate1.pdf"}]}
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": NGMDB_PAGE,
                     "https://pubs.usgs.gov/pubs-services/publication/b1537C": plates})
    r = pdfs.resolve(gq, f, email=None)
    assert [c["via"] for c in r["candidates"]] == ["pubs_usgs", "pubs_usgs"]
    # A report (not a map) never gets scans when it has text.
    r = pdfs.resolve({**gq, "kind": "publication"},
                     FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": NGMDB_PAGE,
                                  "https://pubs.usgs.gov/pubs-services/publication/b1537C": PUBS_B1537C}))
    assert [c["via"] for c in r["candidates"]] == ["pubs_usgs"]


def test_resolve_falls_back_to_ngmdb_scans():
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": NGMDB_PAGE.split("<script")[0].replace("pubs.usgs", "x")
                     + NGMDB_PAGE[NGMDB_PAGE.index("<script"):],
                     "https://pubs.usgs.gov/pubs-services/publication/?": {"records": []}})
    r = pdfs.resolve(CHS, f, email=None)
    assert [c["via"] for c in r["candidates"]] == ["ngmdb_scan", "ngmdb_scan"]


def test_resolve_usgs_doi_and_title_search():
    doi_rec = rec("ngmdb:7", CHS["bbox"], doi="https://doi.org/10.3133/ofr0049")
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": "<html></html>",
                     "https://pubs.usgs.gov/pubs-services/publication/ofr0049": {
                         "indexId": "ofr0049", "links": [
                             {"type": {"text": "Index Page"}, "url": "https://pubs.usgs.gov/of/2000/of00-049/"}]},
                     "https://pubs.usgs.gov/of/2000/of00-049/": '<a HREF="ChapC/Dorchester.pdf">x</a><a href="a.zip">',
                     })
    r = pdfs.resolve(doi_rec, f, email=None)
    assert r["candidates"] == [{"url": "https://pubs.usgs.gov/of/2000/of00-049/ChapC/Dorchester.pdf",
                                "via": "pubs_index"}]

    title_rec = rec("ngmdb:8", CHS["bbox"])
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": "<html></html>",
                     "https://pubs.usgs.gov/pubs-services/publication/?": {"records": [
                         {"indexId": "x1", "title": "Title ngmdb:8", "publicationYear": "2000"}]},
                     "https://pubs.usgs.gov/pubs-services/publication/x1": {"indexId": "x1", "links": [
                         {"type": {"text": "Plate"}, "url": "https://pubs.usgs.gov/x1/plate1.pdf"}]}})
    r = pdfs.resolve(title_rec, f, email=None)
    assert r["candidates"] == [{"url": "https://pubs.usgs.gov/x1/plate1.pdf", "via": "pubs_usgs"}]


def test_unpaywall_used_only_with_email_and_never_logged(monkeypatch):
    journal = rec("ngmdb:9", CHS["bbox"], publisher="Geological Society of America",
                  doi="https://doi.org/10.1130/0091-7613(1989)017")
    route = {"https://ngmdb.usgs.gov/Prodesc/": "<html></html>",
             "https://api.unpaywall.org/v2/": {"is_oa": True, "best_oa_location": {
                 "url_for_pdf": "https://repo.example.edu/paper.pdf", "license": "cc-by"}}}
    r = pdfs.resolve(journal, FakeFetcher(route), email=None)
    assert r["candidates"] == [] and "unpaywall_skipped" in r["checked"]

    f = FakeFetcher(route)
    logs = []
    r = pdfs.resolve(journal, f, email=EMAIL, log=logs.append)
    assert r["candidates"] == [{"url": "https://repo.example.edu/paper.pdf", "via": "unpaywall"}]
    assert any("api.unpaywall.org/v2/10.1130" in c and EMAIL.replace("@", "%40") in c or EMAIL in c
               for c in f.calls)
    assert "unpaywall" in r["checked"]
    assert all(EMAIL not in json.dumps(x) for x in (r, logs))


def test_redact():
    assert EMAIL not in pdfs.redact(f"failed https://api.unpaywall.org/v2/x?email={EMAIL}", EMAIL)
    assert "%40" not in pdfs.redact("email=someone%40example.org", EMAIL)


# --- running ------------------------------------------------------------------

@pytest.fixture
def pdf_bytes(tmp_path):
    return make_pdf(tmp_path / "src.pdf", [["Wando Formation, clayey sand, as much as 30 ft thick."]]).read_bytes()


def _setup(tmp_path, catalog):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps(catalog))
    return dict(catalog_path=cat, checkpoint_dir=tmp_path / ".checkpoints" / "pdfs",
                cache_dir=tmp_path / ".cache", review_dir=tmp_path / "data" / "review", pilot_bbox=PILOT)


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler-utils not installed")
def test_run_downloads_text_checkpoints_and_resumes(tmp_path, pdf_bytes, monkeypatch):
    monkeypatch.setenv("CONTACT_EMAIL", EMAIL)
    chs = rec("ngmdb:1", CHS["bbox"], pdf=["https://pubs.usgs.gov/a.pdf"])
    nope = rec("ngmdb:5", PIEDMONT["bbox"], publisher="Some Society")
    paths = _setup(tmp_path, [nope, chs])
    f = FakeFetcher({"https://pubs.usgs.gov/a.pdf": pdf_bytes, "https://ngmdb.usgs.gov/Prodesc/": "<html></html>",
                     "https://pubs.usgs.gov/pubs-services/publication/?": {"records": []}})
    logs = []
    status = pdfs.run(fetcher=f, ocr=None, log=logs.append, **paths)
    assert status["by_status"] == {"text": 1, "needs_access": 1}
    ck = json.loads((paths["checkpoint_dir"] / "ngmdb_1.json").read_text())
    assert ck["status"] == "text" and ck["pages"] == 1 and ck["kept_chars"] > 0
    text = json.loads((paths["cache_dir"] / "text" / "ngmdb_1.json").read_text())
    assert "Wando Formation" in text["pages"][0]["text"]
    assert (paths["cache_dir"] / "pdfs" / "ngmdb_1").is_dir()

    need = json.loads((paths["review_dir"] / "needs_access.json").read_text())
    assert [n["id"] for n in need["records"]] == ["ngmdb:5"]
    assert need["records"][0]["citation"] == "Citation for ngmdb:5"
    assert set(need["records"][0]) >= {"id", "title", "authors", "year", "citation", "checked", "reason"}
    assert "pages" not in need["records"][0]  # metadata only, never text

    # Nothing but needs_access.json under data/, and no secret anywhere.
    data_files = [p for p in (tmp_path / "data").rglob("*") if p.is_file()]
    assert data_files == [paths["review_dir"] / "needs_access.json"]
    for p in tmp_path.rglob("*.json"):
        assert EMAIL not in p.read_text()
    assert all(EMAIL not in l for l in logs)

    # Resume: nothing is fetched again.
    n_calls = len(f.calls)
    pdfs.run(fetcher=f, ocr=None, log=logs.append, **paths)
    assert len(f.calls) == n_calls


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler-utils not installed")
def test_document_with_an_unread_scan_waits_for_ocr(tmp_path, pdf_bytes):
    scan = make_pdf(tmp_path / "scan.pdf", [[]]).read_bytes()  # a sheet with no text layer
    chs = rec("ngmdb:1", CHS["bbox"], pdf=["https://pubs.usgs.gov/a.pdf", "https://pubs.usgs.gov/plate.pdf"])
    paths = _setup(tmp_path, [chs])
    f = FakeFetcher({"https://pubs.usgs.gov/a.pdf": pdf_bytes, "https://pubs.usgs.gov/plate.pdf": scan,
                     "https://ngmdb.usgs.gov/Prodesc/": "<html></html>",
                     "https://pubs.usgs.gov/pubs-services/publication/?": {"records": []}})
    status = pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, **paths)
    assert status["by_status"] == {"needs_ocr": 1}
    ck = json.loads((paths["checkpoint_dir"] / "ngmdb_1.json").read_text())
    assert ck["unread_files"] == 1 and "OCR" in ck["reason"]


def test_run_rejects_non_pdf_downloads(tmp_path):
    chs = rec("ngmdb:1", CHS["bbox"], pdf=["https://pubs.usgs.gov/a.pdf"])
    paths = _setup(tmp_path, [chs])
    f = FakeFetcher({"https://pubs.usgs.gov/a.pdf": b"<html>login</html>",
                     "https://ngmdb.usgs.gov/Prodesc/": "<html></html>",
                     "https://pubs.usgs.gov/pubs-services/publication/?": {"records": []}})
    status = pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, **paths)
    assert status["by_status"] == {"needs_access": 1}
    ck = json.loads((paths["checkpoint_dir"] / "ngmdb_1.json").read_text())
    assert "not a PDF" in ck["reason"]


def test_resolve_only_limit_and_time_budget(tmp_path):
    catalog = [rec(f"ngmdb:{i}", CHS["bbox"], publisher="Some Society") for i in range(10, 15)]
    paths = _setup(tmp_path, catalog)
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": "<html></html>"})
    s = pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, resolve_only=True, limit=2, **paths)
    assert s["processed_this_run"] == 2
    s = pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, resolve_only=True, max_minutes=0, **paths)
    assert s["processed_this_run"] == 0
    s = pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, resolve_only=True, **paths)
    assert s["processed_this_run"] == 3 and s["by_status"] == {"needs_access": 5}


def test_stale_resolver_version_is_resolved_again(tmp_path):
    paths = _setup(tmp_path, [rec("ngmdb:21", CHS["bbox"], publisher="Some Society")])
    ck = paths["checkpoint_dir"] / "ngmdb_21.json"
    ck.parent.mkdir(parents=True)
    ck.write_text(json.dumps({"id": "ngmdb:21", "status": "needs_access", "candidates": [], "checked": ["catalog"]}))
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": "<html></html>"})
    s = pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, resolve_only=True, **paths)
    assert s["processed_this_run"] == 1
    assert json.loads(ck.read_text())["resolver_version"] == pdfs.RESOLVER_VERSION
    s = pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, resolve_only=True, **paths)
    assert s["processed_this_run"] == 0


def test_needs_access_keeps_entries_from_earlier_runs(tmp_path):
    paths = _setup(tmp_path, [rec("ngmdb:20", CHS["bbox"], publisher="Some Society")])
    review = paths["review_dir"]
    review.mkdir(parents=True)
    (review / "needs_access.json").write_text(json.dumps({"records": [{"id": "ngmdb:99", "title": "older"}]}))
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": "<html></html>"})
    pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, resolve_only=True, **paths)
    ids = [r["id"] for r in json.loads((review / "needs_access.json").read_text())["records"]]
    assert ids == ["ngmdb:20", "ngmdb:99"]


def test_needs_access_drops_records_that_are_now_merged(tmp_path):
    merged = rec("ngmdb:21", CHS["bbox"], publisher="Some Society", gems_download="https://x/gems.zip")
    paths = _setup(tmp_path, [rec("ngmdb:20", CHS["bbox"], publisher="Some Society"), merged])
    review = paths["review_dir"]
    review.mkdir(parents=True)
    (review / "needs_access.json").write_text(json.dumps({"records": [{"id": "ngmdb:21", "title": "now merged"}]}))
    f = FakeFetcher({"https://ngmdb.usgs.gov/Prodesc/": "<html></html>"})
    pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, resolve_only=True, **paths)
    ids = [r["id"] for r in json.loads((review / "needs_access.json").read_text())["records"]]
    assert ids == ["ngmdb:20"]


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler-utils not installed")
def test_drop_pdfs_after_text_keeps_cache_small(tmp_path, pdf_bytes):
    chs = rec("ngmdb:1", CHS["bbox"], pdf=["https://pubs.usgs.gov/a.pdf"])
    paths = _setup(tmp_path, [chs])
    f = FakeFetcher({"https://pubs.usgs.gov/a.pdf": pdf_bytes, "https://ngmdb.usgs.gov/Prodesc/": "<html></html>",
                     "https://pubs.usgs.gov/pubs-services/publication/?": {"records": []}})
    pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, drop_pdfs=True, **paths)
    assert not list((paths["cache_dir"] / "pdfs").rglob("*.pdf"))
    assert (paths["cache_dir"] / "text" / "ngmdb_1.json").exists()
    ck = json.loads((paths["checkpoint_dir"] / "ngmdb_1.json").read_text())
    assert ck["status"] == "text" and ck["pdfs_dropped"] is True
    n = len(f.calls)
    pdfs.run(fetcher=f, ocr=None, log=lambda *a: None, drop_pdfs=True, **paths)
    assert len(f.calls) == n  # done documents are not downloaded again


def test_queue_skips_excluded_ids(monkeypatch):
    ids = [r["id"] for r in pdfs.queue([CHS, COASTAL], PILOT, exclude={"ngmdb:1"})]
    assert ids == ["ngmdb:4"]
    monkeypatch.setattr(pdfs, "excluded_ids", lambda: {"ngmdb:4"})
    assert [r["id"] for r in pdfs.queue([CHS, COASTAL], PILOT)] == ["ngmdb:1"]
