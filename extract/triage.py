"""Page triage: decide which pages to SKIP and how to rank the rest.

This only says what kind of page something is (blank, title, table of
contents, index, reference list, content) so packets can leave out pages
with nothing to extract. It never decides any value; the reading model does.
Reference lists are kept because the schema collects references cited.
"""

from __future__ import annotations

import re

_KEYWORDS = re.compile(
    r"formation|member|group|unit|clay|sand|silt|gravel|limestone|marl|shell|gneiss|schist|granite|fault|"
    r"strike|dip|aquifer|well|boring|auger|core|depth|thick|feet|ft\b|meters?|pleistocene|holocene|miocene|"
    r"eocene|oligocene|pliocene|cretaceous|paleozoic|contact|bed\b|beds\b|munsell|uscs|spt|water level",
    re.I)
_PAGE_NO = re.compile(r"[ivxlc\d]+$", re.I)


def _has_leader(line: str) -> bool:
    """A contents line: text, dot leaders or a wide gap, then a page number.

    Written without nested whitespace quantifiers: -layout lines can hold thousands
    of spaces, and a regex like (\\s{3,})\\s* backtracks cubically on them.
    """
    s = line.rstrip()
    m = _PAGE_NO.search(s)
    if not m or m.start() == 0:
        return False
    before = s[: m.start()]
    gap = len(before) - len(before.rstrip())
    return gap >= 3 or before.rstrip().endswith(("...", "…", ". ."))
_INDEX_LINE = re.compile(r"^\s*[A-Z][^,]{1,60},\s*\d+(?:\s*[-,]\s*\d+)*\s*$")
_REF_LINE = re.compile(r"^\s*[A-Z][A-Za-z'’\-]+,\s+(?:[A-Z]\.\s*){1,3}.*\b(1[89]\d\d|20\d\d)[a-z]?\b")
_REF_HEAD = re.compile(r"^\s*(references?(\s+cited)?|selected references|literature cited|bibliography|"
                       r"works cited)\s*$", re.I | re.M)


def _lines(text: str) -> list[str]:
    return [l for l in text.splitlines() if l.strip()]


def classify(text: str, page: int, n_pages: int, method: str = "pdf_text", min_chars: int = 25) -> dict:
    """{'kind', 'keep', 'score'} for one page."""
    body = text or ""
    chars = len(re.sub(r"\s+", "", body))
    if method == "none" and chars < min_chars:
        return {"kind": "needs_ocr", "keep": False, "score": 0.0}
    if chars < min_chars:
        return {"kind": "blank", "keep": False, "score": 0.0}
    lines = _lines(body)
    head = "\n".join(lines[:4]).lower()
    n = max(len(lines), 1)
    score = round(1000 * (len(_KEYWORDS.findall(body)) + 0.2 * len(re.findall(r"\d", body))) / max(chars, 1), 2)

    leaders = sum(_has_leader(l) for l in lines) / n
    if re.search(r"\b(contents|illustrations|figures|tables|plates)\b", head) and leaders >= 0.4:
        return {"kind": "toc", "keep": False, "score": score}
    if re.search(r"^\s*index\s*$", head, re.M) and sum(bool(_INDEX_LINE.match(l)) for l in lines) / n >= 0.4:
        return {"kind": "index", "keep": False, "score": score}
    refs = sum(bool(_REF_LINE.match(l)) for l in lines)
    if (_REF_HEAD.search("\n".join(lines[:6])) and refs >= 1) or refs / n >= 0.3:
        return {"kind": "references", "keep": True, "score": round(score * 0.3, 2)}
    if page <= 2 and chars < 600:
        return {"kind": "title", "keep": True, "score": score}
    return {"kind": "content", "keep": True, "score": score}
