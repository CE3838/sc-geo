"""Crossref DOI lookup and open-access copies (Unpaywall, OpenAlex, Crossref licenses)."""

import json
from pathlib import Path

import pytest

from harvest import openaccess as oa
from harvest import pdfs

FIX = Path(__file__).parent / "fixtures" / "crossref"
EMAIL = "someone@example.org"


def fx(name):
    return json.loads((FIX / name).read_text())


def items(name):
    return fx(name)["message"]["items"]


WEEMS = {"id": "ngmdb:58683", "title": "Structural and tectonic setting of the Charleston, South Carolina, region: "
         "evidence from the Tertiary stratigraphic record", "authors": "Weems, R.E., and Lewis, W.C.", "year": 2002,
         "publisher": "Geological Society of America", "availability": {"pdf": [], "doi": None, "scgs_ftp": []},
         "ngmdb_url": "https://ngmdb.usgs.gov/Prodesc/proddesc_58683.htm", "kind": "map"}
RHEA = {**WEEMS, "id": "ngmdb:63397", "title": "Evidence of uplift near Charleston, South Carolina",
        "authors": "Rhea, Susan", "year": 1989}
ROCKVILLE = {**WEEMS, "id": "ngmdb:100343", "title": "Geologic Map of the Rockville Quadrangle, Charleston County, "
             "South Carolina", "authors": "Doar, W.R., III", "year": 2006, "publisher": "South Carolina Geological Survey"}
STALLSVILLE = {**WEEMS, "id": "ngmdb:526", "title": "Geologic map of the Stallsville quadrangle, Dorchester and "
               "Charleston Counties, South Carolina", "authors": "Weems, R.E., and Lemon, E.M.", "year": 1984,
               "publisher": "U.S. Geological Survey"}


# --- matching --------------------------------------------------------------------

def test_token_set_ratio():
    assert oa.token_set_ratio("Evidence of uplift near Charleston, S.C.", "evidence of UPLIFT near charleston s c") == 1.0
    assert oa.token_set_ratio("Geologic map of the Rockville quadrangle", "Geologic map of the Ladson quadrangle") < 0.9


def test_first_surname():
    assert oa.first_surname("Weems, R.E., and Lewis, W.C.") == "weems"
    assert oa.first_surname("Van Nieuwenhuise, D.S.") == "van nieuwenhuise"
    assert oa.first_surname("") is None


def test_match_accepts_title_year_and_first_author():
    m = oa.match(WEEMS, items("crossref_match.json"))
    assert m["status"] == "match"
    assert m["doi"] == "10.1130/0016-7606(2002)114<0024:satsot>2.0.co;2"
    assert m["title_score"] >= 0.9 and m["author_check"] == "first author" and m["year"] == 2002
    assert m["container"] == "Geological Society of America Bulletin"
    assert m["publisher"] == "Geological Society of America"


def test_match_rhea_1989():
    m = oa.match(RHEA, items("crossref_geology1989.json"))
    assert m["status"] == "match" and m["doi"].startswith("10.1130/0091-7613(1989)017")


def test_wrong_first_author_is_rejected():
    m = oa.match({**RHEA, "authors": "Marple, R.T."}, items("crossref_geology1989.json"))
    assert m["status"] == "no_match"


def test_year_must_be_within_one():
    assert oa.match({**WEEMS, "year": 2003}, items("crossref_match.json"))["status"] == "match"
    assert oa.match({**WEEMS, "year": 2004}, items("crossref_match.json"))["status"] == "no_match"


def test_no_match_for_scgs_map():
    m = oa.match(ROCKVILLE, items("crossref_nomatch.json"))
    assert m["status"] == "no_match"
    assert m["best"]["doi"]  # the nearest candidate is kept for the record, with its score
    assert m["best"]["title_score"] < 0.9


def test_short_title_contained_in_a_longer_one_is_not_a_match():
    m = oa.match({**WEEMS, "title": "Structural and tectonic setting"}, items("crossref_match.json"))
    assert m["status"] == "no_match"


def test_ambiguous_match_is_not_chosen():
    m = oa.match(WEEMS, items("crossref_ambiguous.json"))
    assert m["status"] == "ambiguous" and "doi" not in m
    assert len(m["candidates"]) == 2


def test_crossref_record_without_authors_needs_an_exact_title_and_year():
    m = oa.match(STALLSVILLE, items("crossref_nomatch.json"))
    assert m["status"] == "match" and m["doi"] == "10.3133/gq1581"
    assert m["author_check"] == "no authors in Crossref"
    assert oa.match({**STALLSVILLE, "year": 1985}, items("crossref_nomatch.json"))["status"] == "no_match"


# --- open copies ---------------------------------------------------------------------

class Fake:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def json(self, url):
        self.calls.append(url)
        for k, v in self.routes.items():
            if url.startswith(k):
                if isinstance(v, Exception):
                    raise v
                return v
        raise OSError("HTTP Error 404")

    def text(self, url):
        return self.json(url)


def test_open_copies_in_order_unpaywall_openalex_crossref(tmp_path):
    item = items("crossref_cc_by.json")[0]
    f = Fake({oa.UNPAYWALL: fx("unpaywall_oa.json"), oa.OPENALEX: fx("openalex_usgs.json")})
    c = oa.open_copies("10.5555/open.example.1", item, f, EMAIL, tmp_path)
    assert [x["via"] for x in c] == ["unpaywall", "openalex", "crossref_oa"]
    assert c[0]["url"] == "https://repository.example.edu/bitstream/1/paper.pdf"
    assert c[1]["url"] == "https://pubs.usgs.gov/of/2013/1030/pdf/ofr2013-1030.pdf"
    assert c[2] == {"url": "https://journal.example.org/article/1/fulltext.pdf", "via": "crossref_oa",
                    "license": "http://creativecommons.org/licenses/by/4.0/"}


def test_closed_article_has_no_open_copy(tmp_path):
    item = items("crossref_match.json")[0]
    f = Fake({oa.UNPAYWALL: fx("unpaywall_closed.json"), oa.OPENALEX: fx("openalex_closed.json")})
    assert oa.open_copies(item["DOI"], item, f, EMAIL, tmp_path) == []


def test_without_email_unpaywall_is_skipped_but_openalex_is_used(tmp_path):
    f = Fake({oa.OPENALEX: fx("openalex_usgs.json")})
    c = oa.open_copies("10.3133/ofr20131030", {}, f, None, tmp_path)
    assert [x["via"] for x in c] == ["openalex"]
    assert not any(u.startswith(oa.UNPAYWALL) for u in f.calls)


def test_shadow_libraries_are_never_used():
    for url in ("https://sci-hub.se/10.1/x", "https://libgen.rs/x.pdf", "https://annas-archive.org/md5/x",
                "https://z-library.sk/book/1"):
        assert not oa.allowed(url)
    assert oa.allowed("https://pubs.usgs.gov/of/2013/1030/pdf/ofr2013-1030.pdf")


def test_closed_crossref_license_is_ignored():
    item = items("crossref_cc_by.json")[0] | {"license": [{"URL": "https://www.elsevier.com/tdm/userlicense/1.0/"}]}
    assert oa.crossref_open_links(item) == []


# --- caching, secrets and integration -------------------------------------------------

def test_lookup_is_cached_and_never_stores_the_email(tmp_path):
    f = Fake({oa.CROSSREF: fx("crossref_match.json")})
    m1 = oa.lookup(WEEMS, f, EMAIL, tmp_path)
    m2 = oa.lookup(WEEMS, f, EMAIL, tmp_path)
    assert m1 == m2 and len(f.calls) == 1
    assert "mailto=" in f.calls[0]  # polite pool
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert EMAIL not in p.read_text()


def test_resolve_uses_crossref_for_records_without_open_text(tmp_path, monkeypatch):
    monkeypatch.setattr(oa, "CACHE", tmp_path)
    f = Fake({"https://ngmdb.usgs.gov/Prodesc/": "<html></html>", oa.CROSSREF: fx("crossref_cc_by.json"),
              oa.OPENALEX: fx("openalex_closed.json")})
    rec = {**WEEMS, "title": items("crossref_cc_by.json")[0]["title"][0]}
    r = pdfs.resolve(rec, f, email=None)
    assert [c["via"] for c in r["candidates"]] == ["crossref_oa"]
    assert r["crossref"]["doi"] == "10.5555/open.example.1" and r["crossref"]["status"] == "match"
    assert "crossref" in r["checked"] and "openalex" in r["checked"]


def test_usgs_doi_from_crossref_leads_to_the_publications_warehouse(tmp_path, monkeypatch):
    monkeypatch.setattr(oa, "CACHE", tmp_path)
    f = Fake({"https://ngmdb.usgs.gov/Prodesc/": "<html></html>",
              "https://pubs.usgs.gov/pubs-services/publication/?": {"records": []},
              oa.CROSSREF: fx("crossref_nomatch.json"),
              "https://pubs.usgs.gov/pubs-services/publication/gq1581": {"links": [
                  {"type": {"text": "Plate"}, "url": "https://pubs.usgs.gov/gq/1581/plate-1.pdf"}]}})
    r = pdfs.resolve(STALLSVILLE, f, email=None)
    assert r["candidates"] == [{"url": "https://pubs.usgs.gov/gq/1581/plate-1.pdf", "via": "pubs_usgs"}]


def test_needs_access_is_annotated_with_doi_and_score(tmp_path, monkeypatch):
    monkeypatch.setattr(oa, "CACHE", tmp_path / "api")
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps([{**WEEMS, "bbox": [-80.5, 32.4, -79.4, 33.2], "series": "", "series_key": None,
                                "scale": None, "themes": [], "quadrangles": [], "citation": "C", "keywords": [],
                                "status": "published"}]))
    f = Fake({"https://ngmdb.usgs.gov/Prodesc/": "<html></html>", oa.CROSSREF: fx("crossref_match.json"),
              oa.OPENALEX: fx("openalex_closed.json")})
    review = tmp_path / "review"
    pdfs.run(catalog_path=cat, checkpoint_dir=tmp_path / "ck", cache_dir=tmp_path / "cache", review_dir=review,
             fetcher=f, ocr=None, log=lambda *a: None, resolve_only=True, workers=1)
    rec = json.loads((review / "needs_access.json").read_text())["records"][0]
    assert rec["crossref"]["doi"] == "10.1130/0016-7606(2002)114<0024:satsot>2.0.co;2"
    assert rec["crossref"]["title_score"] >= 0.9 and rec["crossref"]["status"] == "match"
