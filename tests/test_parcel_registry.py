import json
from pathlib import Path

import pytest

from harvest import parcel_registry as pr

ROOT = Path(__file__).resolve().parent.parent
URL = "https://gis.example.test/arcgis/rest/services/Parcels/MapServer/4"
AGOL = "https://services9.arcgis.com/abc/arcgis/rest/services/Parcels/FeatureServer/0"
SC_COUNTIES = 46

LAYER = {
    "name": "Parcels",
    "type": "Feature Layer",
    "geometryType": "esriGeometryPolygon",
    "objectIdField": "OBJECTID",
    "maxRecordCount": 1000,
    "supportedQueryFormats": "JSON, geoJSON",
    "advancedQueryCapabilities": {"supportsPagination": True},
    "fields": [{"name": n, "type": "esriFieldTypeString"} for n in
               ["OBJECTID", "PID", "OWNER1", "CALC_ACRES", "SITE_ADDR", "LEGAL"]],
}


def entry(**kw):
    base = {"county": "Testing", "fips": "45999", "status": "needs check", "url": URL, "id_field": "pid",
            "acreage_field": None, "address_fields": [], "record_url": None, "cors": None, "checked": None}
    base.update(kw)
    return base


class FakeNet:
    """Answers like an ArcGIS server; records each request."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise pr.Unreachable("no route")


def ok(body, cors="*"):
    return 200, ({"access-control-allow-origin": cors} if cors else {}), body


def test_ok_layer_sets_status_cors_limits_and_fixes_field_case():
    net = FakeNet({URL: ok(LAYER)})
    e = pr.check_entry(entry(), net, today="2026-10-03")
    assert e["status"] == "ok"
    assert e["cors"] is True
    assert e["id_field"] == "PID"
    assert e["max_record_count"] == 1000
    assert e["geojson"] is True
    assert e["oid_field"] == "OBJECTID"
    assert e["checked"] == "2026-10-03"
    # The browser origin is sent so the CORS answer is the one a browser gets.
    url, headers = net.calls[0]
    assert url == URL + "?f=json"
    assert headers["Origin"] == pr.ORIGIN
    # Provenance for what the check stored.
    prov = e["check_provenance"]
    assert prov["source_id"] == "parcel-service:45999"
    assert prov["locator"] == URL + "?f=json"
    assert prov["extraction_method"] == "gis_import"


def test_acreage_and_address_fields_are_inferred_when_missing_and_flagged():
    e = pr.check_entry(entry(), FakeNet({URL: ok(LAYER)}), today="2026-10-03")
    assert e["acreage_field"] == "CALC_ACRES"
    assert e["address_fields"] == ["SITE_ADDR"]
    assert sorted(e["inferred_fields"]) == ["acreage_field", "address_fields"]
    # Fields given in the registry are kept (case fixed) and not flagged.
    e2 = pr.check_entry(entry(acreage_field="calc_acres", address_fields=["site_addr"]), FakeNet({URL: ok(LAYER)}),
                        today="2026-10-03")
    assert e2["acreage_field"] == "CALC_ACRES"
    assert e2["address_fields"] == ["SITE_ADDR"]
    assert e2.get("inferred_fields", []) == []
    # Owner fields are never picked.
    assert "OWNER1" not in json.dumps(pr.web_entry(e))


def test_missing_id_field_needs_check():
    e = pr.check_entry(entry(id_field="TMS"), FakeNet({URL: ok(LAYER)}), today="2026-10-03")
    assert e["status"] == "needs check"
    assert "TMS" in e["check_note"]


def test_no_cors_header_is_flagged_blocked_for_browsers():
    e = pr.check_entry(entry(), FakeNet({URL: ok(LAYER, cors=None)}), today="2026-10-03")
    assert e["cors"] is False
    assert e["status"] == "blocked"
    assert "CORS" in e["check_note"]


def test_login_required_is_blocked():
    net = FakeNet({URL: ok({"error": {"code": 499, "message": "Token Required"}})})
    e = pr.check_entry(entry(), net, today="2026-10-03")
    assert e["status"] == "blocked"
    assert "Token Required" in e["check_note"]
    e = pr.check_entry(entry(), FakeNet({URL: (403, {}, None)}), today="2026-10-03")
    assert e["status"] == "blocked"


def test_not_a_polygon_layer_or_server_error_needs_check():
    lines = dict(LAYER, geometryType="esriGeometryPolyline")
    assert pr.check_entry(entry(), FakeNet({URL: ok(lines)}), today="x")["status"] == "needs check"
    e = pr.check_entry(entry(), FakeNet({URL: (500, {}, None)}), today="x")
    assert e["status"] == "needs check"
    assert "HTTP 500" in e["check_note"]


def test_unreachable_keeps_status_and_says_so():
    e0 = entry(status="ok", cors=True, checked="2026-01-01")
    e = pr.check_entry(e0, FakeNet({URL: pr.Unreachable("Tunnel connection failed: 403")}), today="2026-10-03")
    assert e["status"] == "ok"
    assert e["checked"] == "2026-01-01"
    assert e["last_attempt"] == "2026-10-03"
    assert "unreachable" in e["check_note"]


def test_entries_without_a_service_are_left_alone():
    e0 = entry(status="no public service", url=None, id_field=None)
    net = FakeNet({})
    assert pr.check_entry(e0, net, today="x") == e0
    assert net.calls == []


def test_terms_are_read_from_the_arcgis_online_item():
    layer = dict(LAYER, serviceItemId="0123456789abcdef0123456789abcdef")
    item = {"licenseInfo": "<p>Data provided <b>as is</b> for reference only.</p>", "accessInformation": "Testing County GIS"}
    net = FakeNet({AGOL: ok(layer), pr.ITEM_URL: ok(item)})
    e = pr.check_entry(entry(url=AGOL), net, today="x")
    assert e["service_terms"] == "Testing County GIS. Data provided as is for reference only."


def test_run_checkpoints_and_resumes(tmp_path):
    reg = {"counties": [entry(county="A", fips="45001"), entry(county="B", fips="45003", url=AGOL)]}
    path = tmp_path / "registry.json"
    web = tmp_path / "web.json"
    path.write_text(json.dumps(reg))
    ckpt = tmp_path / "ckpt"

    class Boom(Exception):
        pass

    def failing(url, headers):
        if url.startswith(AGOL):
            raise Boom("stop")
        return ok(LAYER)

    with pytest.raises(Boom):
        pr.run(path, web, ckpt, fetch=failing, today="2026-10-03", log=lambda *a: None)
    assert len(list(ckpt.rglob("*.json"))) == 1  # county A was saved

    net = FakeNet({URL: ok(LAYER), AGOL: ok(LAYER)})
    out = pr.run(path, web, ckpt, fetch=net, today="2026-10-03", log=lambda *a: None)
    assert [u for u, _ in net.calls if u.startswith(URL)] == []  # A came from the checkpoint
    assert [c["status"] for c in out["counties"]] == ["ok", "ok"]
    saved = json.loads(path.read_text())
    assert saved["counties"][1]["checked"] == "2026-10-03"
    assert json.loads(web.read_text())["counties"][0]["id_field"] == "PID"
    assert not ckpt.exists() or not any(ckpt.rglob("*.json"))


def test_only_option_limits_the_check(tmp_path):
    reg = {"counties": [entry(county="A", fips="45001"), entry(county="B", fips="45003")]}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(reg))
    net = FakeNet({URL: ok(LAYER)})
    out = pr.run(path, tmp_path / "w.json", tmp_path / "c", fetch=net, today="d", log=lambda *a: None, only={"b"})
    assert len(net.calls) == 1
    assert [c["status"] for c in out["counties"]] == ["needs check", "ok"]


def test_contact_email_is_never_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTACT_EMAIL", "someone@example.test")
    reg = {"counties": [entry()]}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(reg))
    lines = []
    seen = []

    def net(url, headers):
        seen.append(headers)
        raise pr.Unreachable(f"refused {url}")

    pr.run(path, tmp_path / "w.json", tmp_path / "c", fetch=net, today="d", log=lambda *a: lines.append(" ".join(map(str, a))))
    assert "someone@example.test" in seen[0]["User-Agent"]
    assert not any("someone@example.test" in line for line in lines)


# --- the committed registry ---------------------------------------------------

REGISTRY = json.loads((ROOT / "config" / "parcel_registry.json").read_text())
WEB = json.loads((ROOT / "web" / "data" / "parcel_registry.json").read_text())


def test_registry_has_every_county_once():
    counties = json.loads((ROOT / "web" / "data" / "sc-counties.geojson").read_text())
    names = sorted(f["properties"]["name"] for f in counties["features"])
    assert len(names) == SC_COUNTIES
    assert sorted(c["county"] for c in REGISTRY["counties"]) == names
    fips = {f["properties"]["name"]: f["properties"]["fips"] for f in counties["features"]}
    for c in REGISTRY["counties"]:
        assert c["fips"] == fips[c["county"]], c["county"]


def test_registry_entries_are_complete():
    for c in REGISTRY["counties"]:
        assert c["status"] in pr.STATUSES, c
        assert c.get("terms"), c["county"]
        assert c.get("discovered_from"), c["county"]
        if c["status"] == "ok":
            assert c["url"] and c["id_field"] and c["cors"] is True and c["checked"], c["county"]
        if c["url"]:
            assert c["url"].startswith("https://"), c["county"]
            assert c["url"].rstrip("/").split("/")[-2] in ("MapServer", "FeatureServer"), c["county"]
        if c.get("record_url"):
            assert c["record_url"].startswith("https://"), c["county"]


def test_charleston_pilot_entry():
    chas = next(c for c in REGISTRY["counties"] if c["county"] == "Charleston")
    assert chas["fips"] == "45019"
    assert chas["url"].startswith("https://gisccapps.charlestoncounty.org/arcgis/rest/services/")
    assert chas["id_field"] == "PID"
    assert chas["record_url"].startswith("https://")


def test_web_copy_matches_the_registry():
    assert WEB == pr.web_registry(REGISTRY)
