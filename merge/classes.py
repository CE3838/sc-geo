"""Display classes for merged map units (derived, so flagged inferred).

`age_class` picks the time interval a unit's age range falls in, splitting
the Pleistocene into early/middle/late because the Coastal Plain terraces
are told apart that way. A range spanning all three parts is 'Pleistocene';
a range spanning other intervals takes the one it overlaps most.
`material_class` groups GeMS GeoMaterial terms and SGMC lithology into a
short legend.
"""

from __future__ import annotations

import re

# (id, younger Ma, older Ma, color), youngest first.
_AGES = [
    ("Holocene", 0.0, 0.0117, "#fff7bc"),
    ("late Pleistocene", 0.0117, 0.129, "#fee391"),
    ("Pleistocene", 0.0117, 2.58, "#fec44f"),
    ("middle Pleistocene", 0.129, 0.774, "#fe9929"),
    ("early Pleistocene", 0.774, 2.58, "#ec7014"),
    ("Pliocene", 2.58, 5.333, "#d9f0a3"),
    ("Miocene", 5.333, 23.03, "#addd8e"),
    ("Oligocene", 23.03, 33.9, "#7fcdbb"),
    ("Eocene", 33.9, 56.0, "#41b6c4"),
    ("Paleocene", 56.0, 66.0, "#1d91c0"),
    ("Cretaceous", 66.0, 145.0, "#7fc64e"),
    ("Jurassic", 145.0, 201.4, "#34b2c9"),
    ("Triassic", 201.4, 251.902, "#812b92"),
    ("Permian", 251.902, 298.9, "#f04028"),
    ("Carboniferous", 298.9, 358.9, "#67a599"),
    ("Devonian", 358.9, 419.2, "#cb8c37"),
    ("Silurian", 419.2, 443.8, "#b3e1b6"),
    ("Ordovician", 443.8, 485.4, "#009270"),
    ("Cambrian", 485.4, 538.8, "#7fa056"),
    ("Neoproterozoic", 538.8, 1000.0, "#feb342"),
    ("Mesoproterozoic", 1000.0, 1600.0, "#fdb462"),
    ("Paleoproterozoic", 1600.0, 2500.0, "#f74370"),
    ("Archean", 2500.0, 4031.0, "#f0047f"),
]
AGE_CLASSES = [{"id": a, "color": c} for a, _, _, c in _AGES] + [{"id": "Unknown", "color": "#bdbdbd"}]
_PLEISTOCENE_PARTS = {"late Pleistocene", "middle Pleistocene", "early Pleistocene"}


def age_class(age_ma) -> str:
    if not age_ma:
        return "Unknown"
    young, old = age_ma
    span = old - young
    hits = []
    for name, y, o, _ in _AGES:
        if name == "Pleistocene":
            continue
        overlap = min(old, o) - max(young, y)
        if span <= 0:
            if y <= young <= o:
                return name
            continue
        if overlap > 0 and overlap / span > 0.05:
            hits.append((overlap, name))
    # Spans the late, middle and early Pleistocene: call it the Pleistocene.
    parts = {n for n, y, o, _ in _AGES if n in _PLEISTOCENE_PARTS and min(old, o) - max(young, y) > 0}
    if len(parts) == 3 and span > 0 and (min(old, 2.58) - max(young, 0.0117)) / span > 0.5:
        return "Pleistocene"
    if not hits:
        return "Unknown"
    names = {n for _, n in hits}
    if len(names) > 1 and names <= _PLEISTOCENE_PARTS:
        return "Pleistocene" if len(names) == 3 else max(hits)[1]
    return max(hits)[1]


MATERIAL_CLASSES = [
    {"id": "Made land", "color": "#9e9e9e"},
    {"id": "Water", "color": "#9ec9e2"},
    {"id": "Marsh and peat", "color": "#6b8e23"},
    {"id": "Eolian sand", "color": "#f6e8b1"},
    {"id": "Coastal and marine sediment", "color": "#f2c46d"},
    {"id": "Alluvium", "color": "#c9a66b"},
    {"id": "Other sediment", "color": "#e6d3a3"},
    {"id": "Sedimentary rock", "color": "#c98b4b"},
    {"id": "Metamorphic rock", "color": "#8e7cc3"},
    {"id": "Igneous rock", "color": "#e06666"},
    {"id": "Unknown", "color": "#bdbdbd"},
]

_RULES = [
    (r"made|human|artificial|fill|spoil", "Made land"),
    (r"^water|water or ice", "Water"),
    (r"peat|muck|marsh|swamp", "Marsh and peat"),
    (r"eolian|aeolian|dune", "Eolian sand"),
    (r"coastal|marine|beach|barrier|shelf|estuar", "Coastal and marine sediment"),
    (r"alluvi|fluvial|floodplain", "Alluvium"),
    (r"metamorph|gneiss|schist|phyllite|slate|quartzite|amphibolite|mylonite|meta", "Metamorphic rock"),
    (r"igneous|intrusive|granit|gabbro|diorite|volcanic|plutonic|syenite", "Igneous rock"),
    (r"sedimentary|limestone|sandstone|conglomerate|shale", "Sedimentary rock"),
    (r"sediment|unconsolidated|sand|clay|gravel|deposit", "Other sediment"),
]


def material_class(props: dict) -> str:
    for text in (props.get("geomaterial"), props.get("lith"), props.get("name")):
        if not text:
            continue
        for pattern, cls in _RULES:
            if re.search(pattern, text, re.I):
                return cls
    return "Unknown"
