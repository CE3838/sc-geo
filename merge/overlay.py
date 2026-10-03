"""Overlay overlapping maps into one seamless layer (needs shapely >= 2).

Maps are taken from most to least detailed (merge.score.priority). Each
map's polygons are kept only where no better map already covers the ground,
so the result has no overlaps. For every kept piece, the other maps covering
it are measured (share of the piece's area) to score agreement, confidence
and the list of alternative interpretations.
"""

from __future__ import annotations

import json
from collections import defaultdict

from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from merge import score
from model.units import Lexicon

MIN_AREA = 1e-10  # about 1 square meter in degrees; smaller slivers are dropped

KEEP = ("source", "source_title", "citation", "scale", "year", "map_unit", "name", "full_name", "formation",
        "unit_name", "age", "age_ma", "geomaterial", "lith", "description", "identity_confidence", "source_id",
        "locator", "extraction_method", "confidence")


def _clean(geom):
    if not geom.is_valid:
        geom = make_valid(geom)
    polys = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type in ("Polygon", "MultiPolygon")]
    return unary_union(polys) if polys else None


def merge(features: list[dict], lex: Lexicon, layer: str) -> list[dict]:
    feats = [f for f in features if f["properties"].get("layer") == layer]
    geoms = [_clean(shape(f["geometry"])) for f in feats]
    keep = [i for i, g in enumerate(geoms) if g is not None and g.area > MIN_AREA]
    feats, geoms = [feats[i] for i in keep], [geoms[i] for i in keep]
    if not feats:
        return []
    tree = STRtree(geoms)
    by_source = defaultdict(list)
    for i, f in enumerate(feats):
        by_source[f["properties"]["source"]].append(i)
    order = sorted(by_source, key=lambda s: score.priority(feats[by_source[s][0]]["properties"]))

    out, covered = [], None
    for src in order:
        idxs = by_source[src]
        for i in idxs:
            piece = geoms[i] if covered is None else _clean(geoms[i].difference(covered))
            if piece is None or piece.is_empty or piece.area <= MIN_AREA:
                continue
            others = []
            for j in tree.query(piece):
                if feats[j]["properties"]["source"] == src:
                    continue
                share = piece.intersection(geoms[j]).area / piece.area
                if share > 0.01:
                    others.append((feats[j]["properties"], share))
            winner = feats[i]["properties"]
            conf = score.confidence(winner, others, lex)
            props = {k: winner.get(k) for k in KEEP}
            props.update(
                layer=layer,
                canonical=lex.canonical(winner.get("formation") or winner.get("name")),
                conf=conf["value"],
                conf_base=conf["base"],
                agreement=conf["agreement"],
                n_sources=conf["sources"],
                research_support=conf["research_support"],
                alternatives=json.dumps(score.alternatives(winner, others, lex)[:5]),
                derived_inferred=True,
            )
            out.append({"type": "Feature", "geometry": mapping(piece), "properties": props})
        union = unary_union([geoms[i] for i in idxs])
        covered = union if covered is None else covered.union(union)
    return out
