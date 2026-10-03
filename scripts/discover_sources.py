"""Inventory of public South Carolina geology sources.

Crawls ScienceBase items, ArcGIS Online items/web maps/apps and ArcGIS
REST services, and prints what each one holds: files (name, size, URL),
layers (name, geometry, record count, fields). Needs network access; run in
GitHub Actions (`.github/workflows/discover-sources.yml`).

    python scripts/discover_sources.py > inventory.json
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "sc-geo-inventory/0.1 (+https://github.com/CE3838/sc-geo)"}

SCIENCEBASE_ITEMS = {
    "sgmc-gems-2026": "67129b25d34eb6a152fc7795",
    "sgmc-2017": "5888bf4fe4b05ccb964bab9d",
    "charleston-surficial-2022": "620d314ed34e6c7e83ba9a2d",
}
ARCGIS_ITEMS = {
    "scgs-geology-of-sc-app": "735411a2f5714f28a424422296f77bb1",
    "scgs-quadrangle-status-webmap": "0e8a629708c646198e88d7880fe4c61f",
    "sgmc-arcgis-online": "6672e543686043d4890ead7ee4665dcc",
}
SERVICE_ROOTS = [
    "https://energy.usgs.gov/arcgis/rest/services/Hosted",
    "https://services2.arcgis.com/FiaPA4ga0iQKduv3/ArcGIS/rest/services/State_Geologic_Map_Compilation_%e2%80%93_Geology/FeatureServer",
]
WEB_PAGES = [
    "https://www.dnr.sc.gov/geology/kml.html",
    "https://www.dnr.sc.gov/geology/digital-data.html",
    "https://mrdata.usgs.gov/geology/state/state.php?state=SC",
    "https://pubs.usgs.gov/of/2013/1030/",
]

seen_services: set[str] = set()


def get(url: str, params: dict | None = None, raw: bool = False):
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return body if raw else json.loads(body)


def safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # report and keep going
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def sciencebase(item_id: str, depth: int = 0) -> dict:
    j = get(f"https://www.sciencebase.gov/catalog/item/{item_id}", {"format": "json"})
    out = {
        "title": j.get("title"),
        "citation": j.get("citation"),
        "files": [{"name": f.get("name"), "size": f.get("size"), "url": f.get("url") or f.get("downloadUri")}
                  for f in j.get("files", [])],
        "links": [{"title": l.get("title"), "uri": l.get("uri")} for l in j.get("webLinks", [])],
        "distribution": [{"name": d.get("name"), "uri": d.get("uri")} for d in j.get("distributionLinks", [])],
    }
    if j.get("hasChildren") and depth < 2:
        kids = safe(get, "https://www.sciencebase.gov/catalog/items",
                    {"parentId": item_id, "format": "json", "max": 100, "fields": "title"})
        out["children"] = {k["id"]: safe(sciencebase, k["id"], depth + 1) for k in kids.get("items", [])} \
            if isinstance(kids, dict) and "items" in kids else kids
    return out


def layer(url: str) -> dict:
    j = get(url, {"f": "json"})
    out = {"name": j.get("name"), "type": j.get("type"), "geometry": j.get("geometryType"),
           "fields": [f["name"] for f in j.get("fields") or []],
           "maxRecordCount": j.get("maxRecordCount"), "copyright": j.get("copyrightText")}
    if j.get("type") == "Feature Layer" or j.get("fields"):
        c = safe(get, f"{url}/query", {"where": "1=1", "returnCountOnly": "true", "f": "json"})
        out["count"] = c.get("count", c)
    return out


def service(url: str) -> dict:
    url = url.rstrip("/")
    m = re.match(r"(.*/(MapServer|FeatureServer|ImageServer))(/\d+)?$", url)
    base = m.group(1) if m else url
    if base in seen_services:
        return {"see": base}
    seen_services.add(base)
    j = get(base, {"f": "json"})
    out = {"description": (j.get("serviceDescription") or j.get("description") or "")[:500],
           "copyright": j.get("copyrightText"), "layers": {}, "tables": {}}
    for kind in ("layers", "tables"):
        for l in j.get(kind) or []:
            out[kind][f"{l['id']}:{l.get('name')}"] = safe(layer, f"{base}/{l['id']}")
    return out


def operational_urls(webmap: dict) -> list[str]:
    urls = []
    def walk(layers):
        for l in layers or []:
            if l.get("url"):
                urls.append(l["url"])
            walk(l.get("layers"))
    walk(webmap.get("operationalLayers"))
    return urls


def arcgis_item(item_id: str, host="https://www.arcgis.com") -> dict:
    meta = get(f"{host}/sharing/rest/content/items/{item_id}", {"f": "json"})
    out = {k: meta.get(k) for k in ("title", "owner", "type", "url", "snippet", "accessInformation", "licenseInfo")}
    data = safe(get, f"{host}/sharing/rest/content/items/{item_id}/data", {"f": "json"})
    if isinstance(data, dict):
        # Apps point at a web map; web maps list operational layers.
        values = data.get("values") if isinstance(data.get("values"), dict) else {}
        app_map = data.get("map") if isinstance(data.get("map"), dict) else {}
        wm = values.get("webmap") or app_map.get("itemId")
        if wm:
            out["webmap"] = {wm: safe(arcgis_item, wm, host)}
        urls = operational_urls(data)
        if urls:
            out["operational_layers"] = urls
            out["services"] = {u: safe(service, u) for u in urls}
    if out.get("url") and re.search(r"(Map|Feature|Image)Server", out["url"] or ""):
        out["services"] = {**out.get("services", {}), out["url"]: safe(service, out["url"])}
    return out


def folder(root: str) -> dict:
    j = get(root, {"f": "json"})
    if "layers" in j:
        return service(root)
    return {"services": [s.get("name") + "/" + s.get("type") for s in j.get("services", [])],
            "folders": j.get("folders")}


def links(url: str) -> list[str]:
    html = get(url, raw=True).decode("utf-8", "replace")
    found = set(re.findall(r'href="([^"]+)"', html))
    keep = [urllib.parse.urljoin(url, h) for h in found
            if re.search(r"\.(zip|kml|kmz|gdb|shp|json|pdf)$|MapServer|FeatureServer|sciencebase|doi", h, re.I)]
    return sorted(keep)


def main() -> None:
    inv = {
        "sciencebase": {k: safe(sciencebase, v) for k, v in SCIENCEBASE_ITEMS.items()},
        "arcgis_items": {k: safe(arcgis_item, v) for k, v in ARCGIS_ITEMS.items()},
        "service_roots": {u: safe(folder, u) for u in SERVICE_ROOTS},
        "pages": {u: safe(links, u) for u in WEB_PAGES},
    }
    json.dump(inv, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
