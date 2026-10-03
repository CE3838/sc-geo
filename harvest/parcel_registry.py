"""Check the county parcel service registry (config/parcel_registry.json).

The registry lists one entry per South Carolina county with the county's
public parcel layer (ArcGIS REST), the field that holds the tax map parcel
ID (TMS/PIN), optional acreage and address fields and a link to the
county's public record. The viewer queries these services live for the area
on screen; parcel data is never downloaded into this repo.

For each entry with a service URL this job reads the layer description
(``?f=json``) the way a browser on the public site would (with an Origin
header) and records whether the layer answers, whether the ID field is
there, whether the CORS header allows browser queries, the maximum record
count and the GeoJSON support, then sets the status and a checked date. A
service the checker cannot reach (network or firewall) keeps its status.

The job is resumable: each checked entry is saved under the checkpoint
directory and skipped on the next run; checkpoints are removed after a
complete run. 46 small requests finish in minutes.

    python -m harvest.parcel_registry [--only Charleston,York] [--web-only]
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import socket
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Callable

from model.provenance import ExtractionMethod, StoredValue

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "parcel_registry.json"
WEB_COPY = ROOT / "web" / "data" / "parcel_registry.json"
CHECKPOINTS = ROOT / ".checkpoints" / "parcel_registry"

# The public viewer's origin: CORS answers are checked for it.
ORIGIN = "https://wyatt0119-tech.github.io"
ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/"
STATUSES = ("ok", "no public service", "blocked", "needs check")

# Fields the viewer needs (web/data/parcel_registry.json).
WEB_FIELDS = ("county", "fips", "status", "url", "id_field", "acreage_field", "address_fields", "record_url",
              "record_link_field", "viewer_url", "cors", "geojson", "max_record_count", "oid_field", "note")

# Names tried, in order, when the registry gives no acreage or address field.
ACREAGE_NAMES = ("ACRES", "ACREAGE", "CALC_ACRES", "CALCACRES", "GIS_ACRES", "GISACRES", "CALCULATED_ACREAGE",
                 "CALCULATEDACRES", "DEEDACRES", "DEED_ACRES", "LEGAL_ACRES", "TOTAL_ACRES", "ACRES_GIS")
ADDRESS_NAMES = ("SITE_ADDR", "SITEADDR", "SITE_ADDRESS", "SITUS", "SITUS_ADDR", "SITUSADDRESS", "PROPERTYADDRESS",
                 "PROPERTY_ADDRESS", "PROP_ADDR", "PROPADDR", "LOCATION", "LOC_ADDR", "FULL_ADDRESS",
                 "FULLADDRESS", "ADDRESS", "ADDR_SITE", "PHYSICAL_ADDRESS")

# (status code, lower-case headers, parsed JSON body or None)
Response = tuple[int, dict[str, str], Any]
Fetch = Callable[[str, dict[str, str]], Response]


class Unreachable(OSError):
    """The checker could not reach the server (DNS, firewall, timeout): says
    nothing about the service itself."""


def _headers() -> dict[str, str]:
    agent = "sc-geo-parcel-registry/0.1 (+https://github.com/wyatt0119-tech/sc-geo"
    email = os.environ.get("CONTACT_EMAIL", "").strip()
    return {"User-Agent": f"{agent}; {email})" if email else f"{agent})", "Origin": ORIGIN}


def http_fetch(url: str, headers: dict[str, str], tries: int = 3) -> Response:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                code = resp.status
        except urllib.error.HTTPError as err:
            code, hdrs, raw = err.code, {k.lower(): v for k, v in err.headers.items()}, err.read()
            if code < 500 or attempt == tries - 1:
                return code, hdrs, _json(raw)
            last = err
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as err:
            last = err
        else:
            return code, hdrs, _json(raw)
        time.sleep(2 ** (attempt + 1))
    reason = getattr(last, "reason", last)
    raise Unreachable(f"{type(last).__name__}: {reason}")


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def _plain(text: str | None) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _terms(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    parts = [_plain(item.get(k)) for k in ("accessInformation", "licenseInfo")]
    parts = [p.rstrip(".").strip() for p in parts if p]
    if not parts:
        return None
    text = ". ".join(parts) + "."
    return text if len(text) <= 400 else text[:397].rstrip() + "..."


def _find(fields: dict[str, str], name: str | None) -> str | None:
    return fields.get(name.upper()) if name else None


def check_entry(entry: dict, fetch: Fetch, today: str, headers: dict[str, str] | None = None) -> dict:
    """The entry with its service checked; unchanged when it has no URL."""
    url = entry.get("url")
    if not url:
        return entry
    headers = headers or _headers()
    e = dict(entry)
    probe = f"{url}?f=json"
    try:
        code, hdrs, body = fetch(probe, headers)
    except Unreachable as err:
        e["last_attempt"] = today
        e["check_note"] = f"unreachable from the checker: {err}"
        return e

    e["checked"] = today
    e["check_provenance"] = {k: v for k, v in StoredValue(
        value=None, source_id=f"parcel-service:{entry['fips']}", page=None, locator=probe,
        extraction_method=ExtractionMethod.GIS_IMPORT, confidence=1.0).to_dict().items() if k != "value"}
    e.pop("last_attempt", None)
    error = body.get("error") if isinstance(body, dict) else None
    if code in (401, 403) or (error and error.get("code") in (401, 403, 498, 499)):
        e["status"] = "blocked"
        e["check_note"] = f"service requires a login: {(error or {}).get('message') or f'HTTP {code}'}"
        return e
    if code >= 400 or not isinstance(body, dict) or error:
        e["status"] = "needs check"
        e["check_note"] = f"layer did not answer: {(error or {}).get('message') or f'HTTP {code}'}"
        return e

    fields = {f["name"].upper(): f["name"] for f in body.get("fields") or [] if f.get("name")}
    allow = hdrs.get("access-control-allow-origin")
    e["cors"] = allow in ("*", ORIGIN)
    e["max_record_count"] = body.get("maxRecordCount")
    e["geojson"] = "geojson" in str(body.get("supportedQueryFormats", "")).lower()
    e["oid_field"] = body.get("objectIdField") or next(
        (f["name"] for f in body.get("fields") or [] if f.get("type") == "esriFieldTypeOID"), None)
    paging = (body.get("advancedQueryCapabilities") or {}).get("supportsPagination")
    e["pagination"] = bool(paging) if paging is not None else None

    notes, inferred = [], [k for k in entry.get("inferred_fields", []) if k not in ("acreage_field", "address_fields")]
    id_field = _find(fields, entry.get("id_field"))
    if id_field:
        e["id_field"] = id_field
    else:
        notes.append(f"parcel ID field {entry.get('id_field')!r} is not in the layer")

    if entry.get("acreage_field") and not ("acreage_field" in entry.get("inferred_fields", [])):
        e["acreage_field"] = _find(fields, entry["acreage_field"])
        if not e["acreage_field"]:
            notes.append(f"acreage field {entry['acreage_field']!r} is not in the layer")
    else:
        e["acreage_field"] = next((fields[n] for n in ACREAGE_NAMES if n in fields), None)
        if e["acreage_field"]:
            inferred.append("acreage_field")
    given = entry.get("address_fields") or []
    if given and "address_fields" not in entry.get("inferred_fields", []):
        e["address_fields"] = [f for f in (_find(fields, n) for n in given) if f]
        if len(e["address_fields"]) < len(given):
            notes.append("some address fields are not in the layer")
    else:
        found = next((fields[n] for n in ADDRESS_NAMES if n in fields), None)
        e["address_fields"] = [found] if found else []
        if found:
            inferred.append("address_fields")
    if entry.get("record_link_field"):
        e["record_link_field"] = _find(fields, entry["record_link_field"])
    e["inferred_fields"] = inferred
    if not inferred:
        e.pop("inferred_fields")

    polygon = body.get("geometryType") == "esriGeometryPolygon"
    if not polygon:
        notes.append(f"not a polygon layer ({body.get('geometryType')})")
    if not id_field or not polygon:
        e["status"] = "needs check"
    elif not e["cors"]:
        e["status"] = "blocked"
        notes.append("no CORS header for browser queries from the public site")
    else:
        e["status"] = "ok"

    item_id = body.get("serviceItemId")
    if item_id and re.fullmatch(r"[0-9a-f]{32}", str(item_id)):
        try:
            icode, _, item = fetch(f"{ITEM_URL}{item_id}?f=json", headers)
            if icode == 200 and _terms(item):
                e["service_terms"] = _terms(item)
        except Unreachable:
            pass
    e["check_note"] = "; ".join(notes) if notes else f"layer answers; {len(fields)} fields"
    return e


def web_entry(entry: dict) -> dict:
    return {k: entry.get(k) for k in WEB_FIELDS}


def web_registry(registry: dict) -> dict:
    """The slim copy the viewer reads (no notes on how each entry was checked)."""
    return {
        "note": "Generated from config/parcel_registry.json by python -m harvest.parcel_registry; do not edit.",
        "counties": [web_entry(c) for c in registry["counties"]],
    }


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def run(registry_path: Path = REGISTRY, web_path: Path = WEB_COPY, checkpoint_dir: Path = CHECKPOINTS,
        fetch: Fetch = http_fetch, today: str | None = None, log: Callable[..., None] = print,
        only: set[str] | None = None) -> dict:
    today = today or date.today().isoformat()
    registry = json.loads(Path(registry_path).read_text())
    key = hashlib.sha1(f"{today}|{sorted(only or [])}".encode()).hexdigest()[:12]
    ckpt = Path(checkpoint_dir) / key
    headers = _headers()
    counties = []
    for entry in registry["counties"]:
        name = entry["county"]
        if only and name.lower() not in only:
            counties.append(entry)
            continue
        saved = ckpt / f"{entry['fips']}.json"
        if saved.exists():
            counties.append(json.loads(saved.read_text()))
            continue
        checked = check_entry(entry, fetch, today, headers)
        if entry.get("url"):
            # Never echo headers here; they carry the contact email.
            log(f"{name}: {checked['status']} ({checked.get('check_note', '')})")
        _write_json(saved, checked)
        counties.append(checked)
    registry["counties"] = counties
    registry["checked"] = today
    _write_json(Path(registry_path), registry)
    _write_json(Path(web_path), web_registry(registry))
    shutil.rmtree(ckpt, ignore_errors=True)
    tally: dict[str, int] = {}
    for c in counties:
        tally[c["status"]] = tally.get(c["status"], 0) + 1
    log("statuses: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return registry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="comma-separated county names to check")
    parser.add_argument("--web-only", action="store_true", help="only rewrite web/data/parcel_registry.json")
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--web", type=Path, default=WEB_COPY)
    parser.add_argument("--checkpoints", type=Path, default=CHECKPOINTS)
    args = parser.parse_args()
    if args.web_only:
        _write_json(args.web, web_registry(json.loads(args.registry.read_text())))
        return
    only = {n.strip().lower() for n in args.only.split(",")} if args.only else None
    run(args.registry, args.web, args.checkpoints, only=only)


if __name__ == "__main__":
    main()
