"""Find DOIs with Crossref and legal open-access copies with Unpaywall, OpenAlex and Crossref licenses.

Used by harvest/pdfs.py for catalog records that have no open full text from
NGMDB or the USGS Publications Warehouse:

1. Crossref bibliographic search (title + first author + year). A hit is
   accepted only with a high title similarity (token-set ratio >= 0.9, and
   the shorter title covering most of the longer), a year within 1, and the
   same first-author surname. Crossref records without authors (common for
   USGS series) need a near-identical title (>= 0.97) and the same year. Two
   different DOIs that both pass are "ambiguous" and neither is used.
2. For the DOI, open copies in this order: Unpaywall best OA location (needs
   CONTACT_EMAIL), OpenAlex best OA location, Crossref links whose license is
   Creative Commons. Only publisher, repository and government copies these
   services list; known shadow libraries are refused outright.

Responses are cached under .cache/api (keyed by record or DOI, never by URL,
so the contact email is never written to disk) and requests are rate-limited
to 8 per second per service. The email goes only to the APIs (mailto
parameter) and is never logged.
"""

from __future__ import annotations

import difflib
import json
import re
import threading
import time
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Callable

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works/"
UNPAYWALL = "https://api.unpaywall.org/v2/"
CACHE: Path | None = None  # set by callers (harvest/pdfs.py uses .cache/api); None = no caching
SELECT = "DOI,title,author,issued,container-title,publisher,license,link,type,score"
_SHADOW = re.compile(r"sci-?hub|libgen|library\.lol|z-?lib|zlibrary|annas-archive|booksc\.|\bb-ok\.|1lib\.|"
                     r"libgen|bookfi|scidb", re.I)
_OPEN_LICENSE = re.compile(r"creativecommons\.org/(licenses|publicdomain)", re.I)


# --- text helpers --------------------------------------------------------------

def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _tokens(s: str) -> set[str]:
    return set(_norm(s).split())


def token_set_ratio(a: str, b: str) -> float:
    """Token-set similarity (as in fuzzywuzzy): 1.0 when one title's words equal the other's."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = " ".join(sorted(ta & tb))
    s1 = (inter + " " + " ".join(sorted(ta - tb))).strip()
    s2 = (inter + " " + " ".join(sorted(tb - ta))).strip()
    r = lambda x, y: difflib.SequenceMatcher(None, x, y).ratio()
    return round(max(r(inter, s1), r(inter, s2), r(s1, s2)), 3)


def _coverage(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / max(len(ta), len(tb), 1)


def first_surname(authors: str | None) -> str | None:
    a = (authors or "").strip()
    if not a:
        return None
    first = re.split(r",|\band\b|;", a)[0].strip()
    return _norm(first) or None


def _surname(name: str | None) -> str:
    return re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", _norm(name)).strip()


def year_of(item: dict) -> int | None:
    for key in ("issued", "published-print", "published-online", "created"):
        parts = ((item.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            return int(parts[0])
    return None


# --- matching -----------------------------------------------------------------------

def _info(item: dict, rec: dict) -> dict:
    title = (item.get("title") or [""])[0]
    return {"doi": item.get("DOI"), "title": title, "title_score": token_set_ratio(rec.get("title") or "", title),
            "year": year_of(item), "container": (item.get("container-title") or [None])[0],
            "publisher": item.get("publisher"), "type": item.get("type"),
            "license": [{"URL": l.get("URL"), "content-version": l.get("content-version")}
                        for l in item.get("license") or []],
            "link": [{"URL": l.get("URL"), "content-type": l.get("content-type"),
                      "content-version": l.get("content-version")} for l in item.get("link") or []]}


def match(rec: dict, items: list[dict]) -> dict:
    want = rec.get("title") or ""
    year = int(rec["year"]) if str(rec.get("year") or "").isdigit() else None
    surname = first_surname(rec.get("authors"))
    passing, scored = [], []
    for item in items:
        info = _info(item, rec)
        families = [_surname(a.get("family")) for a in item.get("author") or [] if a.get("family")]
        ok = (info["title_score"] >= 0.9 and _coverage(want, info["title"]) >= 0.75 and year is not None
              and info["year"] is not None and abs(info["year"] - year) <= 1)
        if families:
            info["author_check"] = "first author"
            ok = ok and bool(surname) and (families[0] == surname or families[0].endswith(" " + surname)
                                           or surname.endswith(" " + families[0]))
        else:
            info["author_check"] = "no authors in Crossref"
            ok = ok and info["title_score"] >= 0.97 and info["year"] == year
        scored.append(info)
        if ok:
            passing.append(info)
    if not passing:
        best = max(scored, key=lambda i: i["title_score"], default=None)
        return {"status": "no_match", "best": {k: best[k] for k in ("doi", "title", "title_score", "year")}
                if best else None}
    passing.sort(key=lambda i: -i["title_score"])
    rivals = [p for p in passing[1:] if p["doi"].lower() != passing[0]["doi"].lower()
              and p["title_score"] >= passing[0]["title_score"] - 0.02]
    if rivals:
        return {"status": "ambiguous", "candidates": [{k: p[k] for k in ("doi", "title", "title_score", "year")}
                                                      for p in [passing[0]] + rivals]}
    return {"status": "match", **passing[0]}


# --- fetching -----------------------------------------------------------------------

class _Limiter:
    def __init__(self, per_second: float = 8):
        self.gap, self.next, self.lock = 1 / per_second, 0.0, threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = self.next - now
            self.next = max(now, self.next) + self.gap
        if delay > 0:
            time.sleep(delay)


_LIMITS = {"crossref": _Limiter(), "openalex": _Limiter(), "unpaywall": _Limiter()}


def _safe(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", key)[:180]


def _cached(kind: str, key: str, url: str, fetcher, cache_dir: Path | None):
    path = Path(cache_dir) / kind / f"{_safe(key)}.json" if cache_dir else None
    if path and path.exists():
        return json.loads(path.read_text())
    _LIMITS[kind].wait()
    try:
        data = fetcher.json(url)
    except (OSError, ValueError):
        return None  # not cached: tried again next run
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    return data


def lookup(rec: dict, fetcher, email: str | None, cache_dir: Path | None = None) -> dict:
    """Crossref match for a catalog record (see match())."""
    query = " ".join(str(x) for x in (rec.get("title"), first_surname(rec.get("authors")), rec.get("year")) if x)
    params = {"query.bibliographic": query, "rows": 5, "select": SELECT}
    if email:
        params["mailto"] = email
    data = _cached("crossref", rec["id"], f"{CROSSREF}?{urllib.parse.urlencode(params)}", fetcher, cache_dir)
    if data is None:
        return {"status": "error"}
    return match(rec, (data.get("message") or {}).get("items") or [])


def allowed(url: str | None) -> bool:
    return bool(url) and url.startswith(("http://", "https://")) and not _SHADOW.search(url)


def crossref_open_links(item: dict | None) -> list[dict]:
    lic = [l.get("URL") for l in (item or {}).get("license") or [] if _OPEN_LICENSE.search(l.get("URL") or "")]
    if not lic:
        return []
    out = []
    for l in (item or {}).get("link") or []:
        url = l.get("URL")
        if allowed(url) and ((l.get("content-type") or "").endswith("pdf") or url.lower().endswith(".pdf")):
            out.append({"url": url, "via": "crossref_oa", "license": lic[0]})
    return out


def open_copies(doi: str, item: dict | None, fetcher, email: str | None, cache_dir: Path | None = None,
                log: Callable[..., None] = lambda *a: None) -> list[dict]:
    """Legal open copies of a DOI: Unpaywall (with email), then OpenAlex, then open-licensed Crossref links."""
    out: list[dict] = []

    def add(url, via, **extra):
        if allowed(url) and url not in {c["url"] for c in out}:
            out.append({"url": url, "via": via, **extra})

    q = urllib.parse.quote(doi, safe="/()<>;:")
    if email:
        d = _cached("unpaywall", doi, f"{UNPAYWALL}{q}?email={urllib.parse.quote(email)}", fetcher, cache_dir)
        if d and d.get("is_oa"):
            locs = [d.get("best_oa_location") or {}] + list(d.get("oa_locations") or [])
            add(next((l.get("url_for_pdf") for l in locs if l and l.get("url_for_pdf")), None), "unpaywall")
    mail = f"&mailto={urllib.parse.quote(email)}" if email else ""
    d = _cached("openalex", doi, f"{OPENALEX}doi:{q}?select=doi,open_access,best_oa_location{mail}", fetcher, cache_dir)
    if d and (d.get("open_access") or {}).get("is_oa"):
        best = d.get("best_oa_location") or {}
        add(best.get("pdf_url") or d["open_access"].get("oa_url"), "openalex")
    for c in crossref_open_links(item):
        add(c["url"], "crossref_oa", license=c["license"])
    return out
