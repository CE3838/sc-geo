"""Well IDs compared exactly, for placing a site by coordinates printed for the same well elsewhere (merge.wells).

A water-chemistry report often names its wells only by ID ("CHN-101", a USGS site number) and prints their
coordinates nowhere; another document's well table, or the same document's location table on another page,
may print them. This module says when two labels name the same well:

* normalize(label): upper case, dashes and spaces dropped, leading zeros of every number dropped
  ("CHN–0101", "chn 101" and "CHN101" are all CHN-101). Letters and numbers stay in order and apart
  ("CHN-10-1" is not "CHN-101"). A label without a digit is a name, not an ID, and never matches.
* Within one document any normalized ID matches.
* Across documents only IDs that are unique by construction match (shared_keys): South Carolina county well
  numbers (county prefix + number, optional letter suffix: COUNTY_PREFIXES) and 15-digit USGS site numbers.
  A USGS site number printed in the same row (the label's own quote) as the label, alone, is a second ID.
  Local names ("MW-1", "BH33", "Well 3") never match across documents, and names or place descriptions
  never match at all. A USGS site number's digits encode latitude and longitude only approximately; they are
  never used as a location here.
"""
from __future__ import annotations

import re

# County well-number prefixes (three-letter county codes, and the two-letter forms seen in older reports).
# Two IDs match only when the prefix is the same; prefixes are never translated into each other.
COUNTY_PREFIXES = frozenset("""
ABB AIK ALL AND BAM BRN BFT BRK CAL CHN CRK CTR CHE CLA COL DAR DIL DOR EDG FAI FLO GEO GRV GWD HAM HOR
JAS KER LAN LAU LEE LEX MRN MBO MCC NEW OCO ORG PIC RIC SAL SPA SUM UNI WMB YRK AK BW
""".split())

_TOKEN = re.compile(r"[A-Z]+|\d+")
_USGS = re.compile(r"(?<![\d.])\d{15}(?![\d.]?\d)")


def normalize(label) -> str | None:
    """The ID compared without case, spaces, dashes or zero padding; None when the label holds no digit."""
    toks = _TOKEN.findall(str(label or "").upper())
    if not any(t.isdigit() for t in toks):
        return None
    return "-".join((t.lstrip("0") or "0") if t.isdigit() else t for t in toks)


def _usgs_in(text) -> list[str]:
    return _USGS.findall(str(text or ""))


def shared_keys(label_field: dict | None) -> set[str]:
    """Keys under which a label may match a label of another document: county:<ID> and usgs:<15 digits>."""
    if not label_field:
        return set()
    value = label_field.get("value")
    keys: set[str] = set()
    n = normalize(value)
    if n:
        toks = n.split("-")
        if toks[0] in COUNTY_PREFIXES and len(toks) >= 2 and toks[1].isdigit() and (
                len(toks) == 2 or (len(toks) == 3 and toks[2].isalpha() and len(toks[2]) == 1)):
            keys.add(f"county:{n}")
    own = _usgs_in(value)
    if len(own) == 1 and re.fullmatch(r"\s*(USGS\s*)?\d{15}\s*", str(value), re.I):
        keys.add(f"usgs:{own[0]}")
    quote = label_field.get("quote") or ""
    in_row = _usgs_in(quote)
    if len(in_row) == 1 and value is not None and str(value) in quote:
        keys.add(f"usgs:{in_row[0]}")
    return keys


def local_key(label_field: dict | None) -> str | None:
    """Key under which a label may match another label of the same document."""
    n = normalize((label_field or {}).get("value"))
    return f"id:{n}" if n else None
