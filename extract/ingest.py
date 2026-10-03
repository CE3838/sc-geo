"""Verify, normalize and store a reading model's extraction for one document.

    python -m extract.ingest <result.json> [<result-part2.json> ...] [--verify <verify.json>]
    python -m extract.ingest <result.json> --plan-verify      # which values the second pass re-reads

Steps (see extract/README.md for the confidence formula):

1. Validate each result against extract/schema.json; refuse the whole
   document on any schema error.
2. Check every value's quote against the cached text of the page it cites
   (.cache/text/<id>.json), tolerant of whitespace, hyphenation at line
   breaks, ligatures, curly quotes, case and common OCR confusions. A quote
   found only on a neighbouring page, or not at all, is NOT stored; it goes
   to data/review/queue.json.
3. Normalize values with extract/patterns.py (feet, Munsell, USCS, SPT,
   strike/dip, coordinates, Ma ranges, Geolex names).
4. Store each value as a model.provenance.StoredValue (extraction_method
   "llm", source_id = catalog id, page, confidence computed here) plus its
   quote, how the quote matched, and the second-pass verdict.
5. Write data/extracted/<safe-id>.json, update data/review/queue.json and
   mark the document done in .checkpoints/extract.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import random
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from extract import packets, patterns, schema
from extract.packets import safe_id
from merge.score import scale_weight
from model.provenance import ExtractionMethod, StoredValue
from model.units import Lexicon

ROOT = Path(__file__).resolve().parent.parent
CONFIG: dict = json.loads((ROOT / "config" / "extract.json").read_text())
TEXT_DIR = ROOT / ".cache" / "text"
OUT_DIR = ROOT / "data" / "extracted"
REVIEW_DIR = ROOT / "data" / "review"
DONE_DIR = ROOT / ".checkpoints" / "extract"
PACKETS_DIR = ROOT / ".cache" / "packets"


class IngestError(Exception):
    pass


# --- quote matching ----------------------------------------------------------

_PUNCT = str.maketrans({"‘": "'", "’": "'", "‚": "'", "′": "'", "“": '"', "”": '"',
                        "„": '"', "″": '"', "–": "-", "—": "-", "‒": "-", "−": "-",
                        "‐": "-", "‑": "-", "­": None, "´": "'", "`": "'"})


def normalize(s: str, join_hyphens: bool = True) -> str:
    s = unicodedata.normalize("NFKC", s or "").translate(_PUNCT)
    if join_hyphens:
        s = re.sub(r"([A-Za-z])-[ \t]*\n\s*([a-z])", r"\1\2", s)
    else:
        s = re.sub(r"-[ \t]*\n\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s)


def ocr_fold(s: str) -> str:
    """Collapse characters OCR commonly confuses (both sides are folded the same way)."""
    s = s.replace("rn", "m").replace("vv", "w").replace("cl", "d")
    return s.translate(str.maketrans({"0": "o", "1": "l", "|": "l", "!": "l", "i": "l", "5": "s", "8": "b"}))


def _contains(hay: str, needle: str) -> bool:
    if not needle:
        return False
    pat = re.escape(needle)
    if needle[0].isalnum():
        pat = r"(?<![a-z0-9])" + pat
    if needle[-1].isalnum():
        pat += r"(?![a-z0-9])"
    return re.search(pat, hay) is not None


def _fuzzy(hay: str, needle: str, threshold: float = 0.9) -> bool:
    n = len(needle)
    if n < 20 or not hay:
        return False
    width = int(n * 1.15)
    step = max(1, n // 5)
    for start in range(0, max(1, len(hay) - n // 2), step):
        window = hay[start:start + width]
        sm = difflib.SequenceMatcher(None, window, needle, autojunk=False)
        if sm.real_quick_ratio() < threshold or sm.quick_ratio() < threshold:
            continue
        matched = sum(b.size for b in sm.get_matching_blocks())
        if matched / n >= threshold:
            return True
    return False


def _variants(page: dict) -> list[str]:
    cache = page.get("_norm")
    if cache is None:
        cache = []
        for key in ("text", "raw"):
            t = page.get(key) or ""
            if t:
                cache += [normalize(t, True), normalize(t, False)]
        page["_norm"] = cache
    return cache


def find_quote(quote: str, page: dict) -> str | None:
    """'exact', 'ocr' or 'fuzzy' when the quote is on this page, else None."""
    q = normalize(quote)
    if not q:
        return None
    hays = _variants(page)
    if any(_contains(h, q) for h in hays):
        return "exact"
    qa = _alnum(q)
    if len(qa) >= 12 and any(qa in _alnum(h) for h in hays):
        return "exact"
    qf = ocr_fold(q)
    if any(_contains(ocr_fold(h), qf) for h in hays):
        return "ocr"
    qs = re.sub(r"[^a-z0-9 ]+", "", qf)
    for h in hays:
        # A loose match must still contain every number of the quote (up to OCR confusions).
        if _numbers(q) <= _numbers(h) and _fuzzy(re.sub(r"[^a-z0-9 ]+", "", ocr_fold(h)), qs):
            return "fuzzy"
    return None


def _numbers(s: str) -> set[str]:
    """Number tokens, OCR-folded, so '3O' on an OCR page still counts as '30'."""
    return {ocr_fold(t) for t in re.findall(r"[0-9oil|]*\d[0-9oil|]*", s)}


# --- confidence ----------------------------------------------------------------

def map_sheet_pages(doc: dict) -> set[int]:
    """Pages that come from map sheets: NGMDB scans, or files named plate/sheet/map."""
    out: set[int] = set()
    for f in doc.get("files", []):
        name = (f.get("url") or "").rsplit("/", 1)[-1].lower()
        if f.get("via") == "ngmdb_scan" or re.search(r"plate|sheet|map", name):
            out |= set(range(f["first_page"], f["first_page"] + f["pages"]))
    return out


def source_weight(rec: dict, section: str | None = None, cfg: dict = CONFIG, map_sheet: bool = False) -> float:
    """S: map scale for map-unit descriptions read from a map sheet; otherwise the publisher's weight.

    Unit descriptions on a map are generalized to its scale. Report text, a boring log,
    a measured structure or a reference is not, whatever the scale of the report's maps.
    """
    c = cfg["confidence"]
    if section == "units" and map_sheet and rec.get("scale"):
        w = scale_weight(int(rec["scale"]))
    elif (rec.get("publisher") or "").strip() in cfg["trusted_publishers"]:
        w = c["agency_or_journal"]
    else:
        w = c["other_publisher"]
    if rec.get("status") == "draft":
        w = min(w, c["draft"])
    return w


def confidence(rec: dict, method: str, match: str, verdict: str | None, inferred: bool, cfg: dict = CONFIG,
               section: str | None = None, map_sheet: bool = False) -> float:
    c = cfg["confidence"]
    s = source_weight(rec, section, cfg, map_sheet)
    m = c["ocr_factor"] if method == "ocr" else 1.0
    q = {"exact": 1.0, "ocr": 0.95, "fuzzy": c["fuzzy_quote_factor"]}[match]
    v = {"agree": c["verify_agree"], "disagree": c["verify_disagree"], "unclear": c["verify_unclear"],
         None: c["verify_unchecked"]}[verdict]
    i = c["inferred_factor"] if inferred else 1.0
    return round(min(1.0, max(0.0, s * m * q * v * i)), 3)


# --- normalizing ---------------------------------------------------------------

_LENGTH = {"top", "bottom", "thickness", "total_depth", "water_level", "elevation", "head"}


def normalized(path: str, val: dict, lexicon: Lexicon | None):
    field = re.sub(r"\[\d+\]", "", path).split(".")[-1]
    top = path.split("[", 1)[0]
    x = val.get("value")
    if x is None:
        return None
    if field in _LENGTH:
        return patterns.length_ft(x, default_unit=val.get("units"))
    if field == "munsell":
        return patterns.munsell(x)
    if field == "uscs":
        return patterns.uscs(x) or None
    if field == "spt_n":
        return patterns.spt_n(x)
    if field in ("liquid_limit", "plasticity_index", "moisture_content"):
        return patterns.number(x)
    if field == "strike_dip":
        return patterns.strike_dip(x)
    if field == "location":
        return patterns.coordinates(x)
    if field == "age":
        return patterns.age_ma(x)
    if field in ("date", "water_level_date"):
        return patterns.date(x)
    if lexicon and ((top == "units" and field == "name") or field == "unit"):
        return patterns.unit_name(x, lexicon)
    return None


# --- ingest ----------------------------------------------------------------------

def verify_sample(result: dict, fraction: float = CONFIG["verify_sample_fraction"]) -> list[str]:
    """Paths the second pass re-reads: every table value plus a seeded random share of the rest."""
    values = list(schema.iter_values(result))
    table = [p for p, v in values if v.get("table")]
    others = [p for p, v in values if not v.get("table")]
    seed = int(hashlib.sha256(str(result.get("source_id")).encode()).hexdigest()[:12], 16)
    k = math.ceil(fraction * len(others)) if others else 0
    chosen = set(random.Random(seed).sample(others, k)) | set(table)
    return [p for p, _ in values if p in chosen]


def _load_json(path: Path, what: str):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as err:
        raise IngestError(f"cannot read {what} {path}: {err}") from None


def _catalog() -> dict[str, dict]:
    return {r["id"]: r for r in json.loads((ROOT / "data" / "catalog" / "sc_catalog.json").read_text())}


def _lexicon() -> Lexicon:
    return Lexicon(json.loads((ROOT / "data" / "lexicon" / "geolex_sc.json").read_text()))


def _combine(results: list[dict]) -> dict:
    out = {k: results[0].get(k) for k in ("schema_version", "source_id", "reader", "notes") if k in results[0]}
    out["packets"] = [p for r in results for p in r.get("packets", [])]
    notes = [r["notes"] for r in results if r.get("notes")]
    if notes:
        out["notes"] = "\n".join(notes)
    for key in ("units", "observations", "structures", "groundwater", "references"):
        out[key] = [x for r in results for x in r.get(key, [])]
    return out


def _store(node, path: str, ctx: dict):
    """Copy of a result node with each value replaced by its stored form; None when nothing survives."""
    if schema.is_value(node):
        return ctx["values"].get(path)
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            sub = f"{path}.{k}" if path else k
            if v == schema.NOT_STATED:
                continue
            if isinstance(v, (dict, list)):
                stored = _store(v, sub, ctx)
                if stored not in (None, [], {}):
                    out[k] = stored
            elif k == "kind":
                out[k] = v
        has_value = any(k != "kind" for k in out)
        return out if has_value else None
    if isinstance(node, list):
        items = [_store(x, f"{path}[{i}]", ctx) for i, x in enumerate(node)]
        return [x for x in items if x not in (None, {}, [])]
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ingest(result_paths: list[Path], verify_path: Path | None = None, text_dir: Path = TEXT_DIR,
           out_dir: Path = OUT_DIR, review_dir: Path = REVIEW_DIR, catalog: dict | None = None,
           lexicon: Lexicon | None = None, done_dir: Path = DONE_DIR, cfg: dict = CONFIG,
           packets_dir: Path = PACKETS_DIR) -> dict:
    results = [_load_json(p, "result") for p in result_paths]
    for p, r in zip(result_paths, results):
        errs = schema.validate(r)
        if errs:
            raise IngestError(f"{p} does not match extract/schema.json:\n  " + "\n  ".join(errs[:40]))
    ids = {r["source_id"] for r in results}
    if len(ids) != 1:
        raise IngestError(f"results are for more than one document: {sorted(ids)}")
    result = _combine(results)
    sid = result["source_id"]
    catalog = catalog if catalog is not None else _catalog()
    lexicon = lexicon if lexicon is not None else _lexicon()
    rec = catalog.get(sid)
    if rec is None:
        raise IngestError(f"{sid} is not in the catalog")
    text_path = Path(text_dir) / f"{safe_id(sid)}.json"
    if not text_path.exists():
        raise IngestError(f"no cached text for {sid} at {text_path}; run python -m extract.next_batch --id {sid}")
    doc = _load_json(text_path, "text")
    pages = {p["page"]: p for p in doc["pages"]}
    index_path = Path(packets_dir) / safe_id(sid) / "index.json"
    index = _load_json(index_path, "packet index") if index_path.exists() else None
    if result.get("packets"):
        if index is None or "blocks" not in index:
            raise IngestError(f"no packet index for {sid} at {index_path}; run python -m extract.next_batch --id {sid}")
        packet_blocks = {p["file"].removesuffix(".md"): p["blocks"] for p in index["packets"]}
        unknown = [n for n in result["packets"] if n not in packet_blocks]
        if unknown:
            raise IngestError(f"{sid} has no {', '.join(unknown)} in {index_path} (packets: {sorted(packet_blocks)})")
    sheets = map_sheet_pages(doc)

    verdicts: dict[str, dict] = {}
    if verify_path:
        ver = _load_json(verify_path, "verify file")
        if ver.get("source_id") != sid:
            raise IngestError(f"verify file is for {ver.get('source_id')}, not {sid}")
        for c in ver.get("checks", []):
            if c.get("verdict") not in ("agree", "disagree", "unclear"):
                raise IngestError(f"bad verdict in verify file: {c}")
            verdicts[c["path"]] = c

    review: list[dict] = []
    stored: dict[str, dict] = {}
    counts = {"values": 0, "stored": 0, "exact": 0, "ocr": 0, "fuzzy": 0, "quote_not_found": 0, "wrong_page": 0,
              "agree": 0, "disagree": 0, "unclear": 0}

    def queue(path, val, problem, **extra):
        review.append({"source_id": sid, "path": path, "problem": problem, "value": val.get("value"),
                       "page": val.get("page"), "quote": val.get("quote"), "added_at": _now(), **extra})

    for path, val in schema.iter_values(result):
        counts["values"] += 1
        pg = pages.get(val["page"])
        match = find_quote(val["quote"], pg) if pg else None
        if match is None:
            near = [n for n in (val["page"] - 1, val["page"] + 1) if n in pages and find_quote(val["quote"], pages[n])]
            if near:
                counts["wrong_page"] += 1
                queue(path, val, "wrong_page", found_page=near[0])
            else:
                counts["quote_not_found"] += 1
                queue(path, val, "quote_not_found")
            continue
        counts[match] += 1
        check = verdicts.get(path)
        verdict = check["verdict"] if check else None
        if verdict:
            counts[verdict] += 1
        if match in ("ocr", "fuzzy") and pg.get("method") != "ocr":
            queue(path, val, "inexact_quote", match=match)  # the page has a real text layer
        if verdict in ("disagree", "unclear"):
            queue(path, val, f"verify_{verdict}", verify={k: v for k, v in check.items() if k != "path"})
        sv = StoredValue(value=val["value"], source_id=sid, page=val["page"], extraction_method=ExtractionMethod.LLM,
                         confidence=confidence(rec, pg.get("method", "pdf_text"), match, verdict, val["inferred"], cfg,
                                                    section=path.split("[", 1)[0], map_sheet=val["page"] in sheets),
                         inferred=bool(val["inferred"]))
        entry = sv.to_dict() | {"quote": val["quote"], "quote_match": match, "text_method": pg.get("method"),
                                "verification": verdict}
        for k in ("units", "table", "note"):
            if k in val:
                entry[k] = val[k]
        norm = normalized(path, val, lexicon)
        if norm not in (None, [], {}):
            entry["normalized"] = norm
        stored[path] = entry
        counts["stored"] += 1

    ctx = {"values": stored}
    new_sections = {key: _store(result[key], key, ctx) or [] for key in SECTIONS}

    # Which part of the document this result covers (packet blocks, see extract/packets.py).
    all_blocks = index["blocks"] if index else [str(n) for n in sorted(pages)]
    if result.get("packets") and index:
        covered = [b for name in result["packets"] for b in packet_blocks[name]]
    else:
        covered = list(all_blocks)
    whole_pages = {packets.block_page(b) for b in covered if not packets.is_part(b)}
    new_keys = {_vkey(f, v) for f, v in _walk_values(new_sections)}

    out_dir, review_dir = Path(out_dir), Path(review_dir)
    out_path = out_dir / f"{safe_id(sid)}.json"
    prev = _load_json(out_path, "extracted file") if out_path.exists() else {}

    def stale(field: str, val: dict) -> bool:
        """An earlier value re-read now: on a whole page this result covers, or the same quote."""
        return val.get("page") in whole_pages or _vkey(field, val) in new_keys

    merged = {}
    for key in SECTIONS:
        kept = [r for r in (_prune(r, stale) for r in prev.get(key, [])) if r is not None]
        have = {_vkey(f, v) for f, v in _walk_values(kept)}
        fresh = [r for r in (_prune(r, lambda f, v: _vkey(f, v) in have) for r in new_sections[key]) if r is not None]
        merged[key] = kept + fresh

    done = [b for b in all_blocks if b in set(prev.get("blocks_done") or []) | set(covered)]
    complete = set(all_blocks) <= set(done)
    history = (prev.get("ingests") or [])[-49:] + [{"at": _now(), "packets": result.get("packets", []),
                                                     "reader": result.get("reader"), **counts,
                                                     "review_items": len(review)}]
    out = {
        "source_id": sid,
        **{k: rec.get(k) for k in ("title", "citation", "year", "scale", "publisher", "kind")},
        "schema_version": result["schema_version"],
        "extracted_at": prev.get("extracted_at") or _now(),
        "updated_at": _now(),
        "reader": result.get("reader"),
        "packets": list(dict.fromkeys((prev.get("packets") or []) + result.get("packets", []))),
        "blocks_done": done,
        "blocks_total": len(all_blocks),
        "complete": complete,
        "notes": "\n".join(n for n in (prev.get("notes"), result.get("notes")) if n) or None,
        "files": [{k: f.get(k) for k in ("url", "via", "sha256", "pages", "first_page")} for f in doc.get("files", [])],
        "summary": _totals(merged),
        "ingests": history,
        **merged,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")

    qpath = review_dir / "queue.json"
    old = (_load_json(qpath, "review queue") if qpath.exists() else {}).get("items", [])
    items = [i for i in old if not (i.get("source_id") == sid and
                                    (i.get("page") not in pages or i.get("page") in whole_pages or
                                     (i.get("page"), normalize(i.get("quote") or "")) in
                                     {(k[1], k[2]) for k in new_keys}))] + review
    review_dir.mkdir(parents=True, exist_ok=True)
    qpath.write_text(json.dumps({"about": "Extracted values that need a human look (see review/README.md).",
                                 "count": len(items), "items": items}, indent=1, ensure_ascii=False) + "\n")

    if complete:
        done_dir = Path(done_dir)
        done_dir.mkdir(parents=True, exist_ok=True)
        (done_dir / f"{safe_id(sid)}.json").write_text(json.dumps({"id": sid, "done_at": _now(),
                                                                   "summary": out["summary"]}, indent=1))
    return counts | {"review_items": len(review), "complete": complete, "blocks_done": len(done),
                     "blocks_total": len(all_blocks)}


SECTIONS = ("units", "observations", "structures", "groundwater", "references")


def _is_stored(x) -> bool:
    return isinstance(x, dict) and "source_id" in x and "quote" in x and "page" in x


def _walk_values(node, field: str = ""):
    """(field name, stored value) for every stored value under node."""
    if _is_stored(node):
        yield field, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_values(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_values(v, field)


def _vkey(field: str, val: dict) -> tuple:
    return (field, val.get("page"), normalize(val.get("quote") or ""))


def _prune(node, drop):
    """Copy of a stored record without the values drop(field, value) rejects; None when no value is left."""
    def walk(n, field):
        if _is_stored(n):
            return None if drop(field, n) else n
        if isinstance(n, dict):
            out = {}
            for k, v in n.items():
                if isinstance(v, (dict, list)):
                    w = walk(v, k)
                    if w not in (None, [], {}):
                        out[k] = w
                else:
                    out[k] = v
            return out if any(isinstance(v, (dict, list)) for v in out.values()) else None
        if isinstance(n, list):
            items = [walk(x, field) for x in n]
            return [x for x in items if x not in (None, [], {})]
        return n
    return walk(node, "")


def _totals(sections: dict) -> dict:
    vals = [v for _, v in _walk_values(sections)]
    tally = lambda key: {k: sum(v.get(key) == k for v in vals) for k in {v.get(key) for v in vals} if k}
    return {"stored": len(vals), "quote_match": tally("quote_match"), "verification": tally("verification"),
            "inferred": sum(bool(v.get("inferred")) for v in vals)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify and store a reading model's extraction for one document.")
    ap.add_argument("results", nargs="+", type=Path, help="result JSON file(s) for ONE document")
    ap.add_argument("--verify", type=Path, help="second-pass verify JSON")
    ap.add_argument("--plan-verify", action="store_true",
                    help="print the values the second pass must re-read (JSON) and exit")
    args = ap.parse_args(argv)
    try:
        if args.plan_verify:
            results = [_load_json(p, "result") for p in args.results]
            result = _combine(results)
            paths = verify_sample(result)
            checks = [{"path": p, **{k: schema.get_path(result, p)[k] for k in ("value", "page", "quote")}}
                      for p in paths]
            print(json.dumps({"source_id": result["source_id"], "checks": checks}, indent=1, ensure_ascii=False))
            return 0
        summary = ingest(args.results, verify_path=args.verify)
    except IngestError as err:
        print(f"ingest refused: {err}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
