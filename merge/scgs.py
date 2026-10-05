"""Normalize plain-shapefile geologic maps (SCGS / SCDNR FTP packages) to the merge schema.

The South Carolina Geological Survey publishes its 1:24,000 quadrangle maps
on ftp://ftpdata.dnr.sc.gov/gisdata/glc/ as one zip of polygons and one of
lines per quadrangle. These are not GeMS: each is a shapefile whose
attribute table names the map unit in a field of its own choosing (LABEL,
UNIT, ...) and may or may not give a unit name, age or identity confidence.
So the fields are found by name (or, failing that, the column that looks
like map labels, flagged inferred), and what the table lacks is filled in:

  - unit names for the Aiken-area quadrangles from the SCGS informal
    attribute key (data/lexicon/scgs_aiken_key.json), read directly;
  - ages from Geolex for named units, else from the map symbol's leading
    age letters (Q, T, K, CZ, ...), both flagged inferred;
  - positions from the .prj (NAD27 shifted approximately) or, with no .prj,
    from the coordinate system that puts the data inside the catalog's
    quadrangle bounds, flagged inferred.

Every feature lists what was inferred in `inferred_fields`.
"""

from __future__ import annotations

import io
import json
import re
import struct
import zipfile
from functools import lru_cache
from pathlib import Path

from merge import classes, sources
from model import gisio
from model.provenance import ExtractionMethod, StoredValue
from model.units import Lexicon, name_key

ROOT = Path(__file__).resolve().parent.parent
AIKEN_KEY = ROOT / "data" / "lexicon" / "scgs_aiken_key.json"
SC_BBOX = [-83.36, 32.03, -78.54, 35.22]

_CANDIDATES = {
    "unit": ("MapUnit", "MAP_UNIT", "MAPUNIT", "UNIT", "UNITS", "LABEL", "UNIT_LABEL", "UNITLABEL", "MAP_LABEL",
             "MAP_SYMBOL", "MAPSYMBOL", "UNIT_SYMBO", "UNITSYMBOL", "GEO_UNIT", "GEOL_UNIT", "GEOUNIT", "GEOLUNIT",
             "GEOLOGY", "GEOL", "GEO", "ROCKUNIT", "ROCK_UNIT", "FMTN", "MU"),
    "name": ("UNIT_NAME", "UNITNAME", "NAME", "FULL_NAME", "FULLNAME", "FORMATION", "FM_NAME", "GEO_NAME", "GEOL_NAME",
             "ROCK_NAME", "ROCKNAME", "UNIT_DESC", "DESCRIPT", "DESCRIPTION", "DESCR", "DESC_"),
    "age": ("AGE", "UNIT_AGE", "GEO_AGE", "GEOL_AGE", "PERIOD", "EPOCH", "ERA", "SYSTEM"),
    "identity": ("IdentityConfidence", "IdentityCo", "IdeConf", "IDENT_CONF", "IDENTCONF", "ID_CONF", "IDCONF"),
    "id": ("MapUnitPolys_ID", "MapUnitPol", "MUPs_ID", "OBJECTID", "FID", "ID"),
}
# Unit names that say the unit is unconsolidated material (the merge's surficial layer).
_SEDIMENT_NAME = re.compile(r"sediment|\bsands?\b|gravel|\bclays?\b|\bmud|alluvi|colluvi|eolian|marsh|swamp|peat|dune|"
                            r"beach|terrace|lakebed|carolina bay|" + classes.ARTIFICIAL_FILL.pattern, re.I)
_LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9 ,_-]{0,11}$")

# Leading letters of USGS-style map symbols and the age they stand for. Ambiguous letters
# (P: Permian or 'Piedmont'; M: Mississippian or 'mafic'; lower-case lithologic symbols) are left out.
_SYMBOL_AGES = [
    (r"QH", "Holocene"),
    (r"TQ", "Tertiary to Quaternary"),
    (r"Q(?:[a-z0-9]|$)", "Quaternary"),
    (r"T[a-z]", "Tertiary"),
    (r"(?:[LU] )?UK|K[a-z]", "Cretaceous"),  # SCGS 'UKs' is undifferentiated Cretaceous
    (r"CZ", "Cambrian to Neoproterozoic"),
    (r"Z[a-z]", "Neoproterozoic"),
    (r"C[a-z]", "Cambrian"),
    (r"D[a-z]", "Devonian"),
    (r"O[a-z]", "Ordovician"),
    (r"S[a-z]", "Silurian"),
]


def label_age(label: str | None) -> str | None:
    """Age implied by a map symbol's leading letters (an inference), or None."""
    for pattern, age in _SYMBOL_AGES:
        if re.match(pattern, label or ""):
            return age
    return None


def _pick(fields: list[str], names: tuple[str, ...]) -> str | None:
    lower = {f.lower(): f for f in fields}
    return next((lower[n.lower()] for n in names if n.lower() in lower), None)


def detect_fields(rows: list[dict]) -> dict:
    """Which attribute holds the map unit, name, age, identity confidence and feature ID."""
    fields = list(rows[0]) if rows else []
    out = {k: _pick(fields, names) for k, names in _CANDIDATES.items()}
    out["unit_inferred"] = False
    if out["unit"] is None:
        best = None
        for f in fields:
            vals = [r.get(f) for r in rows if r.get(f) not in (None, "")]
            if not vals or not all(isinstance(v, str) for v in vals):
                continue
            share = sum(bool(_LABEL.match(v)) for v in vals) / len(vals)
            distinct = len(set(vals))
            if share >= 0.9 and 2 <= distinct <= 300 and (best is None or share > best[0]):
                best = (share, f)
        if best is None:
            raise ValueError(f"no map unit field among {fields}")
        out["unit"], out["unit_inferred"] = best[1], True
    if out["name"] == out["unit"]:
        out["name"] = None
    return out


@lru_cache(maxsize=1)
def _aiken_key() -> dict:
    data = json.loads(AIKEN_KEY.read_text())
    return {u["label"]: u for u in data["units"]}


def aiken_key() -> dict[str, dict]:
    """SCGS informal attribute key for the Aiken-area quadrangles: label -> {unit_name, locator}."""
    return dict(_aiken_key())


def extent_check(extent: list[float] | None, bbox: list[float] | None, margin: float = 0.02) -> str:
    if not bbox:
        return "no catalog bbox"
    if not extent:
        return "no features"
    w, s, e, n = bbox
    if extent[2] < w or extent[0] > e or extent[3] < s or extent[1] > n:
        return "outside catalog bbox"
    if extent[0] < w - margin or extent[2] > e + margin or extent[1] < s - margin or extent[3] > n + margin:
        return "larger than catalog bbox"
    return "ok"


def extent(features: list[dict]) -> list[float] | None:
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c:
                walk(x)

    for f in features:
        walk(f["geometry"]["coordinates"])
    return [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)] if xs else None


def _shape_type(data: bytes) -> int:
    return struct.unpack("<i", data[32:36])[0] if len(data) >= 100 else 0


def _polygon_layer(zf: zipfile.ZipFile) -> str:
    names = zf.namelist()
    low = [n.lower() for n in names]
    shps = [n[:-4] for n in names if n.lower().endswith(".shp")]
    polys = [b for b in shps if _shape_type(zf.read(b + ".shp")[:100]) in (5, 15, 25)]
    if polys:
        polys.sort(key=lambda b: (not re.search(r"poly|geol|unit", b, re.I), -zf.getinfo(b + ".shp").file_size))
        return polys[0]
    if shps:
        raise ValueError(f"no polygon shapefile (only {', '.join(Path(s).name for s in shps)})")
    if any(".gdb/" in n for n in low):
        raise ValueError("file geodatabase only; reading it needs GDAL")
    if any(n.endswith(".mdb") for n in low):
        raise ValueError("personal geodatabase (.mdb) only; reading it needs GDAL")
    if any(n.endswith(".e00") for n in low):
        raise ValueError("ArcInfo interchange (.e00) only; reading it needs GDAL")
    if any(n.endswith(".adf") for n in low):
        raise ValueError("ArcInfo coverage only; reading it needs GDAL")
    raise ValueError(f"no shapefile in package ({', '.join(names[:5])})")


def _prj_name(prj: str) -> str:
    m = re.search(r'^(?:PROJCS|GEOGCS)\["([^"]+)"', prj.strip())
    if m:
        return m.group(1)
    f = {k.lower(): v for k, v in re.findall(r"^[ \t]*(\w+)[ \t]+(\S.*?)[ \t]*$", prj, re.M)}
    return "ArcInfo " + " ".join(v for v in (f.get("projection"), f.get("zone") or f.get("fipszone"),
                                             f.get("datum"), f.get("units")) if v)


def _bbox_xy(feats: list[dict]) -> list[float]:
    return extent(feats) or [0.0, 0.0, 0.0, 0.0]


def normalize_zip(zf: zipfile.ZipFile, rec: dict, lex: Lexicon | None = None) -> tuple[list[dict], dict]:
    """Features in the merge schema from one shapefile package, and what was read and how."""
    base = _polygon_layer(zf)
    member = Path(base).name
    names = {n.lower(): n for n in zf.namelist()}
    dbf = names.get(f"{base}.dbf".lower())
    raw = list(gisio.read_shapefile(io.BytesIO(zf.read(base + ".shp")),
                                    io.BytesIO(zf.read(dbf)) if dbf else None))
    notes, position_inferred = [], False
    prj_name = names.get(f"{base}.prj".lower())
    if prj_name:
        prj = zf.read(prj_name).decode("latin-1")
        to_ll = gisio.transformer(prj, allow_approximate=True)
        projection = _prj_name(prj)
        note = gisio.datum_note(prj)
        if note:
            notes.append(note)
            position_inferred = True
    else:
        guess, to_ll = gisio.guess_transformer(_bbox_xy(raw), rec.get("bbox") or SC_BBOX)
        projection = f"guessed: {guess}"
        notes.append(f"no .prj; coordinate system {projection} (fits the catalog extent)")
        position_inferred = True

    rows = [f["properties"] for f in raw]
    fields = detect_fields(rows)
    use_key = fields["name"] is None and re.search(r"08glc", member, re.I)
    key = _aiken_key() if use_key else {}
    info_fields = {k: fields[k] for k in ("unit", "name", "age", "identity", "id")}
    if use_key:
        info_fields["name"] = AIKEN_KEY.name
    source = {"id": rec["id"], "title": rec.get("title"), "citation": rec.get("citation") or rec.get("title"),
              "scale": rec.get("scale"), "year": rec.get("year")}

    out = []
    for i, f in enumerate(raw, 1):
        attrs = f["properties"]
        label = str(attrs.get(fields["unit"]) or "").strip()
        if not label:
            continue
        inferred = []
        if fields["unit_inferred"]:
            inferred.append("map_unit")
        name = str(attrs.get(fields["name"]) or "").strip() if fields["name"] else ""
        name_locator = None
        if not name and label in key:
            name, name_locator = key[label]["unit_name"], f"scgs-aiken-key: {key[label]['locator']}"
        name = name or label
        age = str(attrs.get(fields["age"]) or "").strip() if fields["age"] else ""
        if not age and lex is not None:
            entry = lex.resolve(name)
            if entry and entry.get("age"):
                age = entry["age"]
                inferred.append("age")
        if not age:
            age = label_age(label) or ""
            if age:
                inferred.append("age")
        if position_inferred:
            inferred.append("position")
        if rec.get("scale_inferred"):
            inferred.append("scale")
        geomaterial = None
        if _SEDIMENT_NAME.search(name):
            geomaterial = "Unconsolidated sediment (inferred from unit name)"
            inferred.append("geomaterial")
        formation = name if name_key(name)[0] else None
        unit = {"map_unit": label, "name": name, "full_name": None, "formation": formation, "unit_name": name,
                "age": age or None, "geomaterial": geomaterial, "description": None}
        if sources.is_unmapped(unit) or sources.is_unmapped({"name": label}):
            continue
        fid = attrs.get(fields["id"]) if fields["id"] else None
        sv = StoredValue(value=label, source_id=rec["id"], page=None,
                         locator=f"{member}.shp record {i}" + (f" ({fields['id']}={fid})" if fid not in (None, "") else ""),
                         extraction_method=ExtractionMethod.GIS_IMPORT, confidence=1.0)
        geom = {"type": f["geometry"]["type"], "coordinates": gisio.map_coords(f["geometry"]["coordinates"], to_ll)}
        feat = sources.plain_feature(geom, unit, source, sv,
                                     identity_confidence=str(attrs.get(fields["identity"]) or "").strip() or None
                                     if fields["identity"] else None,
                                     inferred_fields=inferred, name_locator=name_locator)
        out.append(feat)
    info = {"file": member, "format": "shapefile", "projection": projection, "fields": info_fields,
            "unit_field_inferred": fields["unit_inferred"], "read": len(raw), "kept": len(out), "notes": notes}
    return out, info
