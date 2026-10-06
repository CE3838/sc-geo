"""Build the reading list: online catalog records ranked by South Carolina geologic relevance.

    python -m extract.reading_list            # write config/reading_list.json and reading_list_scores.json
    python -m extract.reading_list --check    # exit 1 if the committed files are out of date

Each record gets a score from its catalog fields, not from title words
alone: how much of its bounding box lies in South Carolina (open ocean off
the SC coast is not counted against it), SC quadrangles listed, SC or an SC
place named in the title, geologic subject (title words, NGMDB themes and
keywords), map kind and scale, and series or publisher. National and global
compilations whose box is mostly outside SC, and non-geologic subjects
(water quality, streamflow and floods, statistics and economics, biology,
outreach), are penalized. Records at or above THRESHOLD are listed, the
Charleston County pilot area first, then by score. Every other catalog
record is listed in the scores file with the reason it was left out
(records with no open full text are grouped). The result depends only on
the catalog, config/ and web/data/sc-region.geojson, so it is the same on
every run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from harvest import pdfs

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog" / "sc_catalog.json"
REGION_PATH = ROOT / "web" / "data" / "sc-region.geojson"
PILOT_PATH = ROOT / "config" / "pilot_area.json"
LIST_PATH = ROOT / "config" / "reading_list.json"
SCORES_PATH = ROOT / "config" / "reading_list_scores.json"

THRESHOLD = 40
# Atlantic off the Georgia, SC and southern NC coast (lon/lat). Inside it, whatever is not GA, SC or NC
# land is open sea, which does not count against a coastal record's share inside SC.
OFFSHORE = (-81.6, 30.75, -75.5, 34.7)
NATIONAL_AREA = 150.0  # square degrees, about 15 times South Carolina

ABOUT = ("Online catalog records ranked by South Carolina geologic relevance (python -m extract.reading_list): "
         "bbox share inside SC, SC quadrangles, SC places in the title, geologic subject, map scale and series; "
         "national or global compilations and non-geologic subjects are penalized. Charleston County (pilot) "
         "records come first, then by score. Reading sessions take documents in this order; "
         "python -m extract.prep --todo lists the ones not yet read. Scores and the reason every other record "
         "is left out: config/reading_list_scores.json.")


# --- geometry ----------------------------------------------------------------

def _ring_area(pts) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


def _clip(ring, rect) -> list:
    """Sutherland-Hodgman clip of a polygon ring to an axis-aligned rectangle (w, s, e, n)."""
    w, s, e, n = rect
    edges = [(lambda p: p[0] >= w, lambda a, b: (w, a[1] + (b[1] - a[1]) * (w - a[0]) / (b[0] - a[0]))),
             (lambda p: p[0] <= e, lambda a, b: (e, a[1] + (b[1] - a[1]) * (e - a[0]) / (b[0] - a[0]))),
             (lambda p: p[1] >= s, lambda a, b: (a[0] + (b[0] - a[0]) * (s - a[1]) / (b[1] - a[1]), s)),
             (lambda p: p[1] <= n, lambda a, b: (a[0] + (b[0] - a[0]) * (n - a[1]) / (b[1] - a[1]), n))]
    pts = [tuple(p) for p in ring]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    for inside, cross in edges:
        if not pts:
            break
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
        pts = out
    return pts


def _area_in(rings, rect) -> float:
    if rect[2] <= rect[0] or rect[3] <= rect[1]:
        return 0.0
    return sum(_ring_area(_clip(r, rect)) for r in rings)


def _rect_area(r) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _inter(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _rects(bbox) -> list:
    """The bbox as rectangles: two when it crosses the antimeridian (west > east); points get a tiny box."""
    w, s, e, n = bbox
    if n - s < 1e-4:
        s, n = s - 5e-4, n + 5e-4
    if w > e:
        return [(w, s, 180.0, n), (-180.0, s, e, n)]
    if e - w < 1e-4:
        w, e = w - 5e-4, e + 5e-4
    return [(w, s, e, n)]


def _outer_rings(geom) -> list:
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    return [poly[0] for poly in geom["coordinates"]]


@dataclass
class Context:
    sc: list
    land: list  # SC and the neighbouring states that border the offshore box (GA, NC)
    sc_area: float
    pilot_bbox: list
    merged: set = field(default_factory=set)
    excluded: set = field(default_factory=set)

    @classmethod
    def load(cls, catalog: list[dict] | None = None, region_path: Path = REGION_PATH,
             pilot_path: Path = PILOT_PATH) -> "Context":
        if catalog is None:
            catalog = json.loads(CATALOG_PATH.read_text())
        feats = json.loads(Path(region_path).read_text())["features"]
        sc = [r for f in feats if f["properties"].get("role") == "state" for r in _outer_rings(f["geometry"])]
        land = sc + [r for f in feats if f["properties"].get("name") in ("Georgia", "North Carolina")
                     for r in _outer_rings(f["geometry"])]
        return cls(sc=sc, land=land, sc_area=sum(_ring_area(r) for r in sc),
                   pilot_bbox=json.loads(Path(pilot_path).read_text())["bbox"],
                   merged=pdfs.merged_ids(catalog), excluded=pdfs.excluded_ids())


def geography(bbox, ctx: Context) -> dict | None:
    """Box area (sq deg), SC area inside it, open sea inside it, and the share of its non-sea area in SC."""
    if not bbox:
        return None
    rects = _rects(bbox)
    area = sum(_rect_area(r) for r in rects)
    sc = sum(_area_in(ctx.sc, r) for r in rects)
    sea = 0.0
    for r in rects:
        off = _inter(r, OFFSHORE)
        if off[2] > off[0] and off[3] > off[1]:
            sea += max(0.0, _rect_area(off) - _area_in(ctx.land, off))
    land = max(area - sea, 1e-12)
    return {"area": area, "sc": sc, "sea": sea, "share": min(1.0, sc / land) if sc > 0 else 0.0,
            "cover": sc / ctx.sc_area if ctx.sc_area else 0.0}


def sc_share(bbox, ctx: Context) -> float | None:
    g = geography(bbox, ctx)
    return None if g is None else g["share"]


# --- subject -----------------------------------------------------------------

_SC = re.compile(r"south carolina|\bS\.\s?C\.|\bSC\b")
_SC_PLACE = re.compile(
    r"\b(?:[A-Z][a-z]+ )?(?:Abbeville|Aiken|Allendale|Anderson|Bamberg|Barnwell|Beaufort|Berkeley|Calhoun|Charleston|"
    r"Cherokee|Chester|Chesterfield|Clarendon|Colleton|Darlington|Dillon|Dorchester|Edgefield|Fairfield|Florence|"
    r"Georgetown|Greenville|Greenwood|Hampton|Horry|Jasper|Kershaw|Lancaster|Laurens|Lee|Lexington|McCormick|"
    r"Marion|Marlboro|Newberry|Oconee|Orangeburg|Pickens|Richland|Saluda|Spartanburg|Sumter|Union|Williamsburg|"
    r"York) Count(?:y|ies)\b"
    r"|\b(?:Charleston|Savannah River|Hilton Head|Myrtle Beach|Port Royal|Jocassee|ACE Basin|"
    r"Lake Marion|Lake Moultrie|Edisto|Kiawah|Folly Beach|Sullivans Island|Cape Romain|Bulls Bay|Winyah Bay|"
    r"Pee Dee|Santee|Congaree|Wateree|Caesars Head|Table Rock|Haile|Ridgeway|Summerville|Ladson|Parris Island|"
    r"Grand Strand|Lowcountry|Capers Inlet|Orangeburg|Aiken|Beaufort)\b")
_CAROLINA = re.compile(r"\bcarolinas?\b", re.I)

_GEOLOGY = re.compile(
    r"geolog|stratigra|formation|\bmembers?\b|litholog|fault|tecton|structure contour|structure of|"
    r"structural (?:geology|elements|framework|features|map)|deformation structures|seismic|earthquake|gravity|"
    r"magnetic|geophysic|radioactiv|bouguer|pluton|granit|monzonit|gneiss|schist|diabase|\bdikes?\b|slate|"
    r"\bbelts?\b|piedmont|blue ridge|coastal plain|terrace|barrier island|shoreline|sedimentary|sedimentolog|"
    r"depositional|subbottom|\bsands?\b|\bclays?\b|kaolin|"
    r"phosphate|marl|limestone|mineral (?:deposits|resources)|monazite|\bgold\b|isopach|basement|crust|\brift|"
    r"triassic|jurassic|cretaceous|tertiary|paleogene|neogene|paleocene|eocene|oligocene|miocene|pliocene|"
    r"pleistocene|holocene|quaternary|cenozoic|mesozoic|paleozoic|fossil|paleont|ostracod|foraminif|mollus|"
    r"nannofossil|palyno|\bsoils?\b|liquefaction|subsidence|karst|sinkhole|coastal (?:change|erosion)|outcrop|"
    r"quadrangle|geochronolog|dating|\brocks\b|bedrock|mineralog|petrolog|metamorph|igneous|volcan|orogen|appalach|"
    r"deformation|physiograph|landform|geomorph|\bdunes?\b|eolian|sandhills|hydrogeolog|aquitard|aquiclude|"
    r"folio|lafayette", re.I)
_SUBSURFACE = re.compile(r"\bwells?\b|boring|borehole|\bcores?\b|corehole|test hole|drill|\blogs?\b|aquifer|"
                         r"ground[- ]?water|hydraulic|water levels?|artesian|salt-?water encroachment", re.I)
_NONGEO = re.compile(
    r"water[- ]quality|quality of (?:our|the|water)|stream quality|nutrient|pesticide|mercury|bioaccumulation|"
    r"dissolved|chemical|geochemistry of (?:ground[- ]?)?water|aqueous|fluoride|water chemistry|taste and odor|"
    r"streamflow|\bfloods?\b|surface[- ]waters?|runoff|"
    r"suspended[- ]sediment|water use|withdrawals|careers|for kids|invasive|land cover|heat island|microplastic|"
    r"commodity|materials flow|statistic|econom|streamgage|\bgage\b|network|dashboard|streamstats|"
    r"atmospheric deposition|hurricane|\bstorms?\b|\bsurge\b|wetland|scour|bathymetr|dissolved oxygen|redox|"
    r"biogeograph|\bbirds?\b|\bfish(?:es)?\b|ecolog|habitat|sea-level rise|vulnerability|photograph|standards|"
    r"data exchange|reclamation|orphaned|critical mineral|world minerals|\bglobal\b|watershed boundary|"
    r"hydrologic unit|tracer simulation|records of surface|water summary|water priorities|oil and gas|"
    r"enhanced oil recovery|equability|glaciation|ice sheets|coal|thorium|beryllium|spodumene|cobalt|"
    r"radioactive-waste|three-dimensional geologic models|inventory of|low-flow|flow duration|flood stage|catchment|"
    r"influenza|virus|tritium|transpiration|environmental flow|salinity|hydrodynamic|bacteria|"
    r"best management|culvert|ecosystem|rainfall|benthic|invertebrate|limnolog|retention time|flow patterns|"
    r"supply potential|\bbiota\b|floodflow|watershed model|load simulation|storm-tide", re.I)
_DATA_LISTING = re.compile(r"heavy-mineral-concentrate|geochemical samples|analytical results|sidescan sonar|"
                           r"navigation (?:field )?data", re.I)
_KEYWORDS = ("stratigraphy", "isopach", "structure", "geophysics", "aeromagnetic", "gravity", "seismic", "fault",
             "geotechnical", "liquefaction", "coastal", "Quaternary", "surficial", "bedrock", "geochronology",
             "paleontology")

_SCGS_PUBLISHERS = ("South Carolina Geological Survey", "South Carolina Division of Geology",
                    "South Carolina Department of Natural Resources")
_SOCIETY = re.compile(r"Geological Society of America|Carolina Geological Society|American Journal of Science|"
                      r"American Association of Petroleum|Sedimentary Geology|Sedimentary Research|"
                      r"Economic Paleontologists|Journal of Maps|Elsevier|Pergamon|American Geophysical|"
                      r"Wiley|Southeastern Geology|EDMAP|Paleontological Research|College|University", re.I)
_USGS_MAPS = re.compile(r"^USGS (?:GQ|MF|I|SIM|PP|B|GP)-|Professional Paper|Bulletin|Geologic Quadrangle|"
                        r"Miscellaneous Field|Investigations Series|Geophysical Investigations|Folio", re.I)
_USGS_REPORTS = re.compile(r"^USGS (?:OF|OFR|SIR|WRIR|WSP|HA|DS)-|Open-File|Scientific Investigations Report|"
                           r"Water-Resources Investigations|Water-Supply Paper|Hydrologic Investigations Atlas|"
                           r"Data Series", re.I)
_OUTREACH = re.compile(r"Fact Sheet|General Information Product|Techniques and Methods|Data Report|"
                       r"Mineral commodity|Circum-Pacific|Digital Data Series", re.I)


def _series_points(rec: dict) -> tuple[int, str | None]:
    pub = rec.get("publisher") or ""
    key = rec.get("series_key") or ""
    series = rec.get("series") or ""
    label = key or series or pub
    if pub in _SCGS_PUBLISHERS or key.startswith("SCGS"):
        return 10, f"SCGS/SCDNR series ({label})"
    if _OUTREACH.search(series):
        return -10 if re.search(r"commodity", series, re.I) else -5, f"general-audience or methods series ({series})"
    if pub == "U.S. Geological Survey" and _USGS_MAPS.search(key or series):
        return 6, f"USGS geologic series ({label})"
    if pub == "U.S. Geological Survey" and _USGS_REPORTS.search(key or series):
        return 3, f"USGS report series ({label})"
    if _SOCIETY.search(f"{pub} {series}"):
        return 5, f"society, journal or university ({pub})"
    return 0, None


def _scale_points(rec: dict) -> tuple[int, str | None]:
    scale = rec.get("scale")
    if rec.get("kind") != "map" or not scale:
        return 0, None
    label = f"map at 1:{int(scale):,}"
    for limit, pts in ((24000, 10), (62500, 8), (250000, 5), (1000000, 2), (2500000, 0)):
        if scale <= limit:
            return pts, label if pts else None
    return -5, f"small-scale {label}"


def score(rec: dict, ctx: Context) -> dict:
    """{'score', 'include', 'pilot', 'reasons'} for one catalog record."""
    pts, why = 0, []

    def add(n: int, reason: str | None):
        nonlocal pts
        if reason and n:
            pts += n
            why.append(f"{n:+d} {reason}")

    title = rec.get("title") or ""
    g = geography(rec.get("bbox"), ctx)
    if g is None:
        why.append("+0 no bbox")
    else:
        pct = f"{100 * g['share']:.0f}%" if g["share"] >= 0.01 else f"{100 * g['share']:.2f}%"
        n = next((n for limit, n in ((0.6, 35), (0.25, 25), (0.05, 12), (1e-9, 4)) if g["share"] >= limit), 0)
        if n:
            add(n, f"bbox {pct} inside SC")
        else:
            if g["sea"] >= 0.5 * g["area"] and g["area"] < NATIONAL_AREA:
                add(10, "bbox offshore of the SC coast")
            else:
                why.append("+0 bbox outside SC")
        if g["cover"] >= 0.5 and g["share"] < 0.6 and g["area"] <= NATIONAL_AREA:
            add(10, f"covers {100 * g['cover']:.0f}% of SC")
        if g["area"] > NATIONAL_AREA and g["share"] < 0.05:
            add(-30, f"national or global compilation ({g['area']:.0f} sq deg, {pct} in SC)")
    if _SC.search(title):
        add(15, "South Carolina in title")
    elif m := _SC_PLACE.search(title):
        add(12, f"SC place in title ({m.group(0)})")
    elif _CAROLINA.search(title):
        add(6, "Carolina(s) in title")
    if rec.get("quadrangles"):
        add(10, f"{len(rec['quadrangles'])} SC quadrangle(s) listed")

    geo = _GEOLOGY.search(title)
    sub = _SUBSURFACE.search(title)
    non = _NONGEO.search(title)
    if geo:
        add(20, f"geologic subject ({geo.group(0).lower()})")
        if sub:
            add(5, f"subsurface data ({sub.group(0).lower()})")
    elif sub:
        add(12, f"subsurface or hydrogeology ({sub.group(0).lower()})")
    if non and not geo:
        add(-30, f"not geologic ({non.group(0).lower()})")
        why.append("+0 themes, keywords and map scale not counted for a non-geologic subject")
    else:
        if non:
            add(-10, f"partly non-geologic ({non.group(0).lower()})")
        kws = [k for k in _KEYWORDS if k in (rec.get("keywords") or [])]
        if rec.get("themes"):
            add(10, "NGMDB theme " + ", ".join(rec["themes"]))
        if kws:
            add(5, "keywords " + ", ".join(kws[:4]))
        if not (geo or sub or rec.get("themes") or kws):
            add(-10, "no geologic subject in title, themes or keywords")
        add(*_scale_points(rec))
    if data := _DATA_LISTING.search(title):
        add(-15, f"sample or survey data listing ({data.group(0).lower()})")
    add(*_series_points(rec))
    pilot = bool(rec.get("bbox")) and pdfs.tier(rec, ctx.pilot_bbox) == 0
    if pilot:
        why.insert(0, "Charleston County (pilot area): listed first")
    return {"score": pts, "include": pts >= THRESHOLD, "pilot": pilot, "reasons": why}


# --- builder -----------------------------------------------------------------

def _area(bbox) -> float:
    return sum(_rect_area(r) for r in _rects(bbox)) if bbox else 1e9


def build(catalog: list[dict], ctx: Context) -> dict:
    """{'ids': ranked ids, 'scores': {id: score}, 'excluded': {id: reason}} for the whole catalog."""
    scores, excluded, ranked = {}, {}, []
    for rec in sorted(catalog, key=lambda r: r["id"]):
        rid = rec["id"]
        if not (rec.get("availability") or {}).get("online"):
            excluded[rid] = "no open full text listed in the catalog"
            continue
        s = score(rec, ctx)
        scores[rid] = s
        if rid in ctx.merged:
            excluded[rid] = "GIS source merged directly by merge.build, not read as a document"
        elif rid in ctx.excluded:
            excluded[rid] = "left out in config/catalog_exclude.json"
        elif not s["include"]:
            neg = [r.split(" ", 1)[1] for r in s["reasons"] if r.startswith("-")]
            pos = [r.split(" ", 1)[1] for r in s["reasons"] if r.startswith("+") and not r.startswith("+0")]
            why = "; ".join(neg) if neg else "too little SC geologic content (only " + ("; ".join(pos) or "none") + ")"
            excluded[rid] = f"score {s['score']} below {THRESHOLD}: {why}"
        else:
            ranked.append(rec)
    year = lambda r: int(r["year"]) if str(r.get("year") or "").isdigit() else 0
    ranked.sort(key=lambda r: (0 if scores[r["id"]]["pilot"] else 1, -scores[r["id"]]["score"], _area(r.get("bbox")),
                               -year(r), r["id"]))
    return {"ids": [r["id"] for r in ranked], "scores": scores, "excluded": excluded}


def render(out: dict) -> tuple[str, str]:
    """The reading list and the scores file as text (one record per line in the scores file)."""
    listed = json.dumps({"about": ABOUT, "ids": out["ids"]}, indent=1, ensure_ascii=False) + "\n"
    rank = {rid: i + 1 for i, rid in enumerate(out["ids"])}
    order = out["ids"] + sorted((i for i in out["scores"] if i not in rank),
                                key=lambda i: (-out["scores"][i]["score"], i))
    lines = []
    for rid in order:
        s = out["scores"][rid]
        entry = {"id": rid, "rank": rank.get(rid), "score": s["score"], "included": rid in rank}
        if s["pilot"]:
            entry["pilot"] = True
        if rid not in rank:
            entry["excluded"] = out["excluded"][rid]
        entry["reasons"] = s["reasons"]
        lines.append(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    offline = sorted(i for i, why in out["excluded"].items() if i not in out["scores"])
    head = {"about": "Scores behind config/reading_list.json (python -m extract.reading_list). Included records "
                     "in reading order, then excluded ones with the reason. Points: " + _POINTS,
            "threshold": THRESHOLD}
    text = json.dumps(head, ensure_ascii=False)[:-1] + ',\n "records": [\n  ' + ",\n  ".join(lines) + "\n ],\n"
    text += ' "no_open_full_text": ' + json.dumps({"reason": "no open full text listed in the catalog; see "
                                                   "data/review/needs_access.json", "ids": offline}) + "\n}\n"
    return listed, text


_POINTS = ("bbox share of non-sea area inside SC +35/+25/+12/+4 (offshore of SC +10), covers half of SC +10, "
           "national or global compilation -30; South Carolina in title +15, SC place +12, Carolina(s) +6; "
           "SC quadrangles +10; geologic subject +20 (+5 subsurface data), subsurface or hydrogeology only +12; "
           "NGMDB theme +10; geologic keywords +5; none of these -10; non-geologic subject -30 (themes, keywords "
           "and scale then not counted; -10 with a geologic subject); sample or survey data listing -15; "
           "map scale +10 (1:24k) to -5 (smaller than 1:2.5M); series SCGS/SCDNR +10, USGS geologic +6, "
           "USGS report +3, society/journal +5, general-audience or methods -5 (commodity summaries -10).")


def write(out: dict, list_path: Path = LIST_PATH, scores_path: Path = SCORES_PATH) -> None:
    listed, scores = render(out)
    Path(list_path).write_text(listed)
    Path(scores_path).write_text(scores)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed files differ from a fresh build")
    args = ap.parse_args()
    catalog = json.loads(CATALOG_PATH.read_text())
    out = build(catalog, Context.load(catalog))
    if args.check:
        listed, scores = render(out)
        ok = LIST_PATH.read_text() == listed and SCORES_PATH.read_text() == scores
        print("reading list up to date" if ok else "reading list out of date: run python -m extract.reading_list")
        sys.exit(0 if ok else 1)
    write(out)
    print(f"{len(out['ids'])} listed, {len(out['scores']) - len(out['ids'])} online records left out, "
          f"{len(out['excluded']) - (len(out['scores']) - len(out['ids']))} without open full text")


if __name__ == "__main__":
    main()
