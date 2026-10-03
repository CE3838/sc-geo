"""Geologic ages and unit names, for comparing map units across sources.

Ages are converted to numeric ranges (millions of years before present) using
the International Chronostratigraphic Chart (ICS, v2023/09). Named units are
matched by their geographic name ("Wando" in "Wando Fm.") and resolved through
the USGS Geolex lexicon, which maps abandoned names to their replacements.
These conversions are derived values: callers store them flagged inferred.
"""

from __future__ import annotations

import re

AGE_SOURCE = "International Chronostratigraphic Chart v2023/09"

# name -> (younger boundary, older boundary) in Ma.
INTERVALS: dict[str, tuple[float, float]] = {
    "holocene": (0.0, 0.0117),
    "pleistocene": (0.0117, 2.58),
    "late pleistocene": (0.0117, 0.129),
    "middle pleistocene": (0.129, 0.774),
    "chibanian": (0.129, 0.774),
    "early pleistocene": (0.774, 2.58),
    "calabrian": (0.774, 1.80),
    "gelasian": (1.80, 2.58),
    "pliocene": (2.58, 5.333),
    "late pliocene": (2.58, 3.600),
    "piacenzian": (2.58, 3.600),
    "early pliocene": (3.600, 5.333),
    "zanclean": (3.600, 5.333),
    "miocene": (5.333, 23.03),
    "late miocene": (5.333, 11.63),
    "middle miocene": (11.63, 15.98),
    "early miocene": (15.98, 23.03),
    "oligocene": (23.03, 33.9),
    "late oligocene": (23.03, 27.82),
    "chattian": (23.03, 27.82),
    "early oligocene": (27.82, 33.9),
    "rupelian": (27.82, 33.9),
    "eocene": (33.9, 56.0),
    "late eocene": (33.9, 37.71),
    "priabonian": (33.9, 37.71),
    "middle eocene": (37.71, 47.8),
    "bartonian": (37.71, 41.2),
    "lutetian": (41.2, 47.8),
    "early eocene": (47.8, 56.0),
    "ypresian": (47.8, 56.0),
    "paleocene": (56.0, 66.0),
    "quaternary": (0.0, 2.58),
    "neogene": (2.58, 23.03),
    "paleogene": (23.03, 66.0),
    "tertiary": (2.58, 66.0),
    "cenozoic": (0.0, 66.0),
    "cretaceous": (66.0, 145.0),
    "late cretaceous": (66.0, 100.5),
    "early cretaceous": (100.5, 145.0),
    "maastrichtian": (66.0, 72.1),
    "campanian": (72.1, 83.6),
    "santonian": (83.6, 86.3),
    "coniacian": (86.3, 89.8),
    "turonian": (89.8, 93.9),
    "cenomanian": (93.9, 100.5),
    "jurassic": (145.0, 201.4),
    "triassic": (201.4, 251.902),
    "late triassic": (201.4, 237.0),
    "mesozoic": (66.0, 251.902),
    "permian": (251.902, 298.9),
    "carboniferous": (298.9, 358.9),
    "pennsylvanian": (298.9, 323.2),
    "mississippian": (323.2, 358.9),
    "devonian": (358.9, 419.2),
    "silurian": (419.2, 443.8),
    "ordovician": (443.8, 485.4),
    "cambrian": (485.4, 538.8),
    "middle cambrian": (497.0, 509.0),
    "miaolingian": (497.0, 509.0),
    "paleozoic": (251.902, 538.8),
    "phanerozoic": (0.0, 538.8),
    "ediacaran": (538.8, 635.0),
    "cryogenian": (635.0, 720.0),
    "tonian": (720.0, 1000.0),
    "neoproterozoic": (538.8, 1000.0),
    "mesoproterozoic": (1000.0, 1600.0),
    "paleoproterozoic": (1600.0, 2500.0),
    "proterozoic": (538.8, 2500.0),
    "archean": (2500.0, 4031.0),
    "precambrian": (538.8, 4567.0),
}
_MODIFIERS = {"early": "early", "lower": "early", "middle": "middle", "late": "late", "upper": "late"}
_TERM = re.compile(r"\b(?:(early|lower|middle|late|upper)[\s-]+)?(" +
                   "|".join(sorted({k.split()[-1] for k in INTERVALS}, key=len, reverse=True)) + r")\b")


def _interval(modifier: str | None, name: str) -> tuple[float, float] | None:
    if modifier:
        key = f"{_MODIFIERS[modifier]} {name}"
        if key in INTERVALS:
            return INTERVALS[key]
    base = INTERVALS.get(name)
    if base is None or not modifier:
        return base
    # No defined subdivision: take the matching third of the interval.
    young, old = base
    third = (old - young) / 3
    part = {"late": 0, "middle": 1, "early": 2}[_MODIFIERS[modifier]]
    return (young + part * third, young + (part + 1) * third)


def age_range(text: str | None) -> tuple[float, float] | None:
    """(younger, older) in Ma for age text, or None when it names no interval."""
    if not text:
        return None
    t = text.lower().replace("precambrian-proterozoic", "proterozoic")
    # 'early Tertiary (early Oligocene)': the parenthetical is more specific.
    paren = re.findall(r"\(([^)]*)\)", t)
    if paren and any(_TERM.search(p) for p in paren):
        t = " ".join(paren)
    # SGMC hierarchy 'Phanerozoic - Cenozoic - Quaternary - Pleistocene': finest term.
    if re.search(r"\s-\s", t) and not re.search(r"\bto\b|\band\b", t):
        t = re.split(r"\s-\s", t)[-1]
    found = [_interval(m.group(1), m.group(2)) for m in _TERM.finditer(t)]
    found = [f for f in found if f]
    if not found:
        return None
    return (min(f[0] for f in found), max(f[1] for f in found))


def age_overlap(a, b) -> float | None:
    """Share of the narrower range that lies inside the other (0-1)."""
    if a is None or b is None:
        return None
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    narrow = min(a[1] - a[0], b[1] - b[0])
    if narrow <= 0:
        point = a[0] if a[1] - a[0] <= 0 else b[0]
        other = b if a[1] - a[0] <= 0 else a
        return 1.0 if other[0] <= point <= other[1] else 0.0
    return max(0.0, hi - lo) / narrow


# --- names -------------------------------------------------------------------

RANKS = {
    "formation", "member", "group", "supergroup", "bed", "beds", "pluton", "complex", "suite", "sequence",
    "terrane", "belt", "zone", "granite", "gneiss", "schist", "phyllite", "quartzite", "marl", "limestone",
    "sand", "clay", "gravel", "metagranite", "metadiorite", "diorite", "gabbro", "granodiorite", "tonalite",
    "metatonalite", "amphibolite", "mylonite", "metagabbro", "syenite", "metadacite", "melange", "unit",
}
_PLURALS = {"formations": "formation", "members": "member", "groups": "group", "sands": "sand", "clays": "clay",
            "gravels": "gravel", "granites": "granite", "gneisses": "gneiss", "plutons": "pluton"}
_ABBREV = {"fm": "formation", "fms": "formation", "mbr": "member", "gp": "group", "grp": "group", "ls": "limestone",
           "ss": "sandstone"}
GENERIC = {
    "beach", "beaches", "swamp", "marsh", "tidal", "alluvium", "alluvial", "moved", "earth", "water", "terrace",
    "deposits", "deposit", "sediments", "sediment", "undifferentiated", "undivided", "unnamed", "upper", "lower",
    "middle", "coastal", "plain", "eolian", "aeolian", "fill", "made", "land", "lagoonal", "barrier", "dune",
    "dunes", "fluvial", "colluvium", "residuum", "saprolite", "rock", "rocks", "metamorphosed", "mafic", "felsic",
    "intermediate", "ultramafic", "gneissic", "quartz", "biotite", "muscovite", "mica", "garnet", "hornblende",
    "and", "or", "the", "of", "with", "minor", "interlayered", "porphyritic", "megacrystic", "equigranular",
    "metasedimentary", "metavolcanic", "volcanic", "sedimentary", "unconsolidated", "marine", "estuarine",
    "younger", "older", "lowland", "upland", "floodplain", "channel", "bay", "carolina", "bays", "plutonic",
    "island", "islands", "facies", "shelf", "fossiliferous", "clayey", "pebbly", "coarse", "fine", "freshwater",
    "saltmarsh", "salt", "mud", "flat", "flats", "ridge", "ridges", "molluscan", "conglomerate", "fringe", "spoil",
    "phosphate", "artificial", "back", "lagoon", "inlet", "spit", "overwash", "washover", "nearshore", "offshore",
    "upper", "basal", "silty", "sandy", "gravelly", "organic", "peat", "muddy",
}


def _words(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z'’]*", text.lower().replace("’", "'"))
    return [_ABBREV.get(w, _PLURALS.get(w, w)) for w in words]


def name_key(name: str | None) -> tuple[str | None, str | None]:
    """(geographic name, rank) for a unit name; (None, None) for informal units."""
    if not name:
        return (None, None)
    text = re.sub(r"\([^)]*\)", " ", name)
    text = re.split(r"\bof\b", text, maxsplit=1, flags=re.I)[0]
    segments = re.split(r"\s+-\s+|,", text)
    for seg in sorted(segments, key=lambda s: -len(s)):
        first_alt = re.sub(r"/[^\s]+(?:\s+[a-z]+)*?(?=\s+\S+$)", "", seg, flags=re.I)
        words = _words(first_alt)
        ranks = [i for i, w in enumerate(words) if w in RANKS]
        if not ranks:
            continue
        i = ranks[-1]
        key_words = words[:i]
        while key_words and key_words[-1] in RANKS:
            key_words.pop()
        if key_words and not all(w in GENERIC for w in key_words):
            # Drop leading generic words ('Gneissic granite of Starr' already split).
            while key_words and key_words[0] in GENERIC:
                key_words.pop(0)
            return (" ".join(key_words), words[i])
    return (None, None)


class Lexicon:
    """Geolex units keyed by lowercase name; abandoned names point to replacements."""

    def __init__(self, entries: list[dict]):
        self.entries = {e["name"].lower(): e for e in entries}

    def resolve(self, name: str | None) -> dict | None:
        key, _ = name_key(name)
        entry = self.entries.get(key) if key else None
        seen = set()
        while entry and entry.get("replaced_by") and entry["name"] not in seen:
            seen.add(entry["name"])
            # 'Battleground and Blacksburg': follow the first replacement.
            first = re.split(r"\s+(?:and|or)\s+|,", entry["replaced_by"])[0].strip().lower()
            entry = self.entries.get(first, entry)
        return entry

    def canonical(self, name: str | None) -> str | None:
        """Lexicon name if known, else the geographic key, else None (informal)."""
        entry = self.resolve(name)
        if entry:
            return entry["name"]
        return name_key(name)[0]

    def agreement(self, a: dict, b: dict) -> float:
        """How well two unit descriptions agree: 1 same named unit, 0.5/0.25 by age only, 0 conflict."""
        ca, cb = self.canonical(a.get("name")), self.canonical(b.get("name"))
        if ca and cb:
            return 1.0 if ca.lower() == cb.lower() else 0.0
        overlap = age_overlap(age_range(a.get("age")), age_range(b.get("age")))
        if not overlap:
            return 0.0
        return 0.5 if not ca and not cb else 0.25
