"""Normalize geologic map sources into one schema for merging.

Every polygon becomes a feature whose properties follow the same schema,
whatever its source (GeMS packages, the Charleston database, SGMC):

    source, source_title, citation, scale, year       which map, how detailed, when
    map_unit, name, formation, unit_name, full_name   the unit as the map names it
    age, geomaterial, lith, description               as the map describes it
    identity_confidence                               the mapper's certainty
    source_id, locator, extraction_method, confidence provenance (read directly)
    age_ma, layer, derived_inferred                   derived here, flagged inferred

GeMS units that are facies (e.g. "Barrier-island sand facies") take their
formation from the nearest named heading above them in the Description of
Map Units, so they can be matched with the same formation on other maps.
"""

from __future__ import annotations

import re

from merge import score
from model.provenance import ExtractionMethod, StoredValue
from model.units import age_range, name_key


def _field(row: dict, *names: str):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return None


def _hkey_parts(key: str) -> list[str]:
    return [p for p in re.split(r"[-.]", key or "") if p]


def gems_units(dmu: list[dict]) -> dict[str, dict]:
    """MapUnit -> unit description from a GeMS DescriptionOfMapUnits table."""
    by_key = {}
    for row in dmu:
        key = _field(row, "HierarchyKey", "HKey")
        if key:
            by_key[tuple(_hkey_parts(key))] = row
    units = {}
    for row in dmu:
        mu = _field(row, "MapUnit")
        if not mu:
            continue
        parts = tuple(_hkey_parts(_field(row, "HierarchyKey", "HKey") or ""))
        formation = None
        for i in range(len(parts) - 1, 0, -1):
            parent = by_key.get(parts[:i])
            pname = parent and _field(parent, "Name")
            if pname and name_key(pname)[0]:
                formation = pname
                break
        name = _field(row, "Name") or mu
        if formation and not name_key(name)[0]:
            unit_name = f"{formation}, {name[0].lower()}{name[1:]}"
        else:
            unit_name = name
        desc = _field(row, "Description", "Descr")
        units[mu] = {
            "map_unit": mu,
            "name": name,
            "full_name": _field(row, "FullName"),
            "formation": formation,
            "unit_name": unit_name,
            "age": _field(row, "Age"),
            "geomaterial": _field(row, "GeoMaterial", "GeoMat"),
            "description": (desc[:500] + "…") if desc and len(desc) > 500 else desc,
        }
    return units


def _finish(geometry: dict, props: dict) -> dict:
    rng = age_range(props.get("age"))
    props["age_ma"] = list(rng) if rng else None
    props["layer"] = score.layer(props)
    props["derived_inferred"] = True
    return {"type": "Feature", "geometry": geometry, "properties": props}


_UNMAPPED = re.compile(r"\bnot mapped\b|\bunmapped\b", re.I)


def is_unmapped(unit: dict) -> bool:
    """Placeholder polygons for areas the map does not cover (e.g. 'Portions of Georgia not mapped')."""
    return any(_UNMAPPED.search(unit.get(k) or "") for k in ("name", "unit_name", "age", "geomaterial"))


def unit_feature(geometry: dict, attrs: dict, units: dict[str, dict], source: dict) -> dict | None:
    """One GeMS MapUnitPolys polygon in the merge schema, or None for unmapped areas."""
    mu = _field(attrs, "MapUnit") or "?"
    unit = units.get(mu, {"map_unit": mu, "name": mu, "unit_name": mu, "formation": None})
    if is_unmapped(unit):
        return None
    # Shapefile field names are cut to 10 characters (MapUnitPol, IdentityCo).
    poly_id = _field(attrs, "MapUnitPolys_ID", "MapUnitPol", "MUPs_ID", "OBJECTID")
    sv = StoredValue(value=None, source_id=source["id"], page=None,
                     locator=f"MapUnitPolys_ID={poly_id}" if poly_id else f"MapUnit={mu}",
                     extraction_method=ExtractionMethod.GIS_IMPORT, confidence=1.0)
    props = {
        "source": source["id"],
        "source_title": source.get("title"),
        "citation": source.get("citation"),
        "scale": source.get("scale"),
        "year": source.get("year"),
        "map_unit": mu,
        "name": unit.get("name"),
        "full_name": unit.get("full_name"),
        "formation": unit.get("formation"),
        "unit_name": unit.get("unit_name") or mu,
        "age": unit.get("age"),
        "geomaterial": unit.get("geomaterial"),
        "lith": None,
        "description": unit.get("description"),
        "identity_confidence": _field(attrs, "IdentityConfidence", "IdentityCo", "IdeConf"),
        "source_id": sv.source_id,
        "locator": sv.locator,
        "extraction_method": sv.extraction_method.value,
        "confidence": sv.confidence,
    }
    return _finish(geometry, props)


SGMC_SOURCE = {
    "title": "State Geologic Map Compilation (SGMC), South Carolina",
    "citation": "Horton, J.D., San Juan, C.A., and Stoeser, D.B., 2017, The State Geologic Map Compilation (SGMC) "
                "geodatabase of the conterminous United States: USGS Data Series 1052, https://doi.org/10.3133/ds1052.",
    "scale": 500000,
    "year": 2017,
}


def _sgmc_age(p: dict) -> str | None:
    if p.get("unit_age"):
        return p["unit_age"]
    young = (p.get("age_min") or "").split(" - ")[-1].strip()
    old = (p.get("age_max") or "").split(" - ")[-1].strip()
    if not young and not old:
        return None
    return young if (young == old or not old) else (old if not young else f"{old} to {young}")


def sgmc_feature(geometry: dict, p: dict) -> dict:
    """One polygon from harvest/sgmc.py output in the merge schema."""
    props = {
        "source": p.get("source_id") or "usgs-sgmc",
        "source_title": SGMC_SOURCE["title"],
        "citation": SGMC_SOURCE["citation"],
        "scale": SGMC_SOURCE["scale"],
        "year": SGMC_SOURCE["year"],
        "map_unit": (p.get("unit") or "").split(";")[0] or None,
        "name": p.get("name"),
        "full_name": p.get("strat_unit") or None,
        "formation": None,
        "unit_name": p.get("name"),
        "age": _sgmc_age(p),
        "geomaterial": None,
        "lith": p.get("lith"),
        "description": p.get("description") or p.get("major"),
        "identity_confidence": None,
        "source_id": p.get("source_id") or "usgs-sgmc",
        "locator": p.get("locator"),
        "extraction_method": ExtractionMethod.GIS_IMPORT.value,
        "confidence": 1.0,
    }
    return _finish(geometry, props)
