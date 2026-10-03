import json
import os
from pathlib import Path

import pytest

from harvest import sgmc

URL = "https://example.test/arcgis/rest/services/SGMC/FeatureServer/0"

LAYER = {
    "name": "SGMC_Geology",
    "objectIdField": "OBJECTID",
    "maxRecordCount": 2,
    "fields": [{"name": n} for n in [
        "OBJECTID", "STATE", "ORIG_LABEL", "SGMC_LABEL", "UNIT_LINK", "UNIT_NAME", "AGE_MIN", "AGE_MAX",
        "MAJOR1", "MAJOR2", "MAJOR3", "MINOR1", "MINOR2", "MINOR3", "MINOR4", "MINOR5", "REF_ID",
        "REFERENCE", "GENERALIZE", "NGMDB1", "NGMDB2", "NGMDB3"]],
}


def square(x, y):
    return {"type": "Polygon", "coordinates": [[[x, y], [x + 0.1, y], [x + 0.1, y + 0.1], [x, y + 0.1], [x, y]]]}


def feat(oid, **props):
    base = {"OBJECTID": oid, "STATE": "SC", "MAJOR2": None, "MAJOR3": "", "MINOR1": None, "MINOR2": None,
            "MINOR3": None, "MINOR4": None, "MINOR5": None, "NGMDB2": None, "NGMDB3": None}
    base.update(props)
    return {"type": "Feature", "id": oid, "geometry": square(-80 + oid * 0.1, 33), "properties": base}


WANDO = feat(1, ORIG_LABEL="Qw", SGMC_LABEL="Qw;1", UNIT_LINK="SCQw;1", UNIT_NAME="Wando Formation",
             AGE_MIN="Phanerozoic - Cenozoic - Quaternary - Pleistocene",
             AGE_MAX="Phanerozoic - Cenozoic - Quaternary - Pleistocene", MAJOR1="Clay", MINOR1="Sand",
             REF_ID="SC002", REFERENCE="Surficial Geology and Geomorphology of the Atlantic Coastal Plain",
             GENERALIZE="Unconsolidated, undifferentiated", NGMDB1="https://ngmdb.usgs.gov/Prodesc/proddesc_1.htm")
WINNSBORO = feat(2, ORIG_LABEL="Cgw", SGMC_LABEL="Cgw;4", UNIT_LINK="SCCgw;4", UNIT_NAME="Granite - Winnsboro pluton",
                 AGE_MIN="Phanerozoic - Paleozoic - Permian", AGE_MAX="Phanerozoic - Paleozoic - Carboniferous",
                 MAJOR1="Granite", REF_ID="SC001", REFERENCE="Preliminary Geologic Map of the Appalachian Piedmont",
                 GENERALIZE="Igneous, intrusive", NGMDB1=None)
WATER = feat(3, ORIG_LABEL="water", SGMC_LABEL="water;0", UNIT_LINK="SCwater;0", UNIT_NAME="water",
             AGE_MIN=None, AGE_MAX=None, MAJOR1=None, REF_ID="SC001",
             REFERENCE="Preliminary Geologic Map of the Appalachian Piedmont", GENERALIZE="Water", NGMDB1=None)


class FakeServer:
    def __init__(self, features=(WANDO, WINNSBORO, WATER), fail_offsets=()):
        self.features = list(features)
        self.fail_offsets = set(fail_offsets)
        self.calls = []
        self.headers = []

    def __call__(self, url, params, headers):
        self.calls.append(dict(params))
        self.headers.append(headers)
        assert url.startswith(URL)
        if url == URL:
            return LAYER
        assert url == URL + "/query"
        assert params["where"] == "STATE='SC'"
        if params.get("returnCountOnly") == "true":
            return {"count": len(self.features)}
        off = int(params["resultOffset"])
        if off in self.fail_offsets:
            raise OSError("network down")
        n = int(params["resultRecordCount"])
        page = self.features[off:off + n]
        return {"type": "FeatureCollection", "features": page,
                "properties": {"exceededTransferLimit": off + n < len(self.features)}}


def run(tmp_path, server, **kw):
    return sgmc.run(
        urls=[URL], state="SC", out_dir=tmp_path / "out", checkpoint_dir=tmp_path / "ckpt",
        fetch=server, log=kw.pop("log", lambda *_: None), **kw)


def load(tmp_path):
    data = json.loads((tmp_path / "out" / "sgmc-sc.geojson").read_text())
    meta = json.loads((tmp_path / "out" / "sgmc-sc.meta.json").read_text())
    return data, meta


def test_harvest_pages_and_writes_geojson_and_metadata(tmp_path):
    server = FakeServer()
    run(tmp_path, server)
    data, meta = load(tmp_path)
    assert [f["properties"]["unit"] for f in data["features"]] == ["Qw;1", "Cgw;4", "water;0"]
    pages = [c for c in server.calls if "resultOffset" in c]
    assert [p["resultOffset"] for p in pages] == ["0", "2"]
    assert all(p["orderByFields"] == "OBJECTID" and p["f"] == "geojson" and p["outSR"] == "4326" for p in pages)
    assert meta["count"] == 3
    assert meta["source_url"] == URL
    assert meta["references"] == {
        "SC001": "Preliminary Geologic Map of the Appalachian Piedmont",
        "SC002": "Surficial Geology and Geomorphology of the Atlantic Coastal Plain",
    }
    assert "retrieved_at" in meta


def test_feature_properties_and_provenance(tmp_path):
    run(tmp_path, FakeServer())
    data, _ = load(tmp_path)
    p = data["features"][0]["properties"]
    assert p["name"] == "Wando Formation"
    assert p["major"] == "Clay"
    assert p["minor"] == "Sand"
    assert p["lith"] == "Unconsolidated, undifferentiated"
    assert p["age_min"].endswith("Pleistocene")
    assert p["ngmdb"] == "https://ngmdb.usgs.gov/Prodesc/proddesc_1.htm"
    # Provenance for the attributes read from the source.
    assert p["source_id"] == "usgs-sgmc:SC002"
    assert p["locator"] == "OBJECTID=1; UNIT_LINK=SCQw;1"
    assert p["extraction_method"] == "gis_import"
    assert p["confidence"] == 1.0
    # Derived classes are flagged as inferred.
    assert p["age_class"] == "Quaternary"
    assert p["lith_class"] == "Unconsolidated"
    assert p["classes_inferred"] is True


@pytest.mark.parametrize("age,expected", [
    ("Phanerozoic - Cenozoic - Quaternary - Holocene", "Quaternary"),
    ("Phanerozoic - Cenozoic - Tertiary-Neogene - Miocene", "Neogene"),
    ("Phanerozoic - Cenozoic - Tertiary-Paleogene - Eocene", "Paleogene"),
    ("Phanerozoic - Cenozoic - Tertiary", "Tertiary"),
    ("Phanerozoic - Mesozoic - Cretaceous - Late-Cretaceous - Maastrichtian", "Cretaceous"),
    ("Phanerozoic - Mesozoic - Triassic", "Triassic"),
    ("Phanerozoic - Mesozoic", "Mesozoic"),
    ("Phanerozoic - Paleozoic - Carboniferous", "Carboniferous"),
    ("Phanerozoic - Paleozoic - Cambrian - Middle-Cambrian", "Cambrian"),
    ("Phanerozoic - Paleozoic", "Paleozoic"),
    ("preCambrian-Proterozoic - Neoproterozoic", "Neoproterozoic"),
    ("preCambrian-Proterozoic - Mesoproterozoic", "Mesoproterozoic"),
    ("preCambrian", "Precambrian"),
    ("Undetermined", "Unknown"),
    (None, "Unknown"),
])
def test_age_class_uses_the_period(age, expected):
    assert sgmc.age_class(age) == expected


def test_age_and_lith_class_for_water_and_ranges(tmp_path):
    run(tmp_path, FakeServer())
    data, _ = load(tmp_path)
    granite, water = data["features"][1]["properties"], data["features"][2]["properties"]
    # Colored by the oldest age bound (AGE_MAX).
    assert granite["age_class"] == "Carboniferous"
    assert granite["lith_class"] == "Igneous"
    assert water["age_class"] == "Water"
    assert water["lith_class"] == "Water"


def test_resumes_from_checkpoints_after_failure(tmp_path):
    with pytest.raises(OSError):
        run(tmp_path, FakeServer(fail_offsets={2}))
    assert not (tmp_path / "out" / "sgmc-sc.geojson").exists()
    server = FakeServer()
    run(tmp_path, server)
    # Page 0 came from the checkpoint; only page 2 was fetched again.
    assert [c["resultOffset"] for c in server.calls if "resultOffset" in c] == ["2"]
    data, _ = load(tmp_path)
    assert len(data["features"]) == 3


def test_checkpoints_are_cleared_after_success(tmp_path):
    run(tmp_path, FakeServer())
    assert not any((tmp_path / "ckpt").rglob("page-*.json"))
    # So the next run fetches fresh data.
    server = FakeServer()
    run(tmp_path, server)
    assert [c["resultOffset"] for c in server.calls if "resultOffset" in c] == ["0", "2"]


def test_count_mismatch_is_an_error(tmp_path):
    class Short(FakeServer):
        def __call__(self, url, params, headers):
            r = super().__call__(url, params, headers)
            if params.get("returnCountOnly") == "true":
                return {"count": 5}
            return r
    with pytest.raises(RuntimeError, match="expected 5"):
        run(tmp_path, Short())


def test_falls_back_to_next_url(tmp_path):
    def broken(url, params, headers):
        raise OSError("down")
    server = FakeServer()

    def fetch(url, params, headers):
        if url.startswith("https://broken.test"):
            return broken(url, params, headers)
        return server(url, params, headers)
    sgmc.run(urls=["https://broken.test/FeatureServer/0", URL], state="SC", out_dir=tmp_path / "out",
             checkpoint_dir=tmp_path / "ckpt", fetch=fetch, log=lambda *_: None)
    _, meta = load(tmp_path)
    assert meta["source_url"] == URL


def test_contact_email_goes_in_user_agent_but_never_in_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTACT_EMAIL", "secret-person@example.org")
    logged = []
    server = FakeServer()
    run(tmp_path, server, log=lambda *a: logged.append(" ".join(map(str, a))))
    assert all("secret-person@example.org" in h["User-Agent"] for h in server.headers)
    assert logged and not any("secret-person" in line for line in logged)
    _, meta = load(tmp_path)
    assert "secret-person" not in json.dumps(meta)


UNITS = [
    {"STATE": "SC", "UNIT_LINK": "SCQw;1", "REF_ID": "SC002", "PROVINCE": "Coastal Plain",
     "UNIT_AGE": "Pleistocene", "UNITDESC": "Clayey sand and clay, back-barrier", "STRAT_UNIT": "Wando Formation"},
    {"STATE": "SC", "UNIT_LINK": "SCCgw;4", "REF_ID": "SC001", "PROVINCE": "Central Piedmont",
     "UNIT_AGE": "Late Paleozoic", "UNITDESC": "Granite", "STRAT_UNIT": ""},
]


class OfficialServer(FakeServer):
    """Like the official USGS service: no REF_ID on polygons, a Units table instead."""

    def __init__(self):
        strip = lambda f: {**f, "properties": {k: v for k, v in f["properties"].items() if k != "REF_ID"}}
        super().__init__(features=[strip(WANDO), strip(WINNSBORO)])

    def __call__(self, url, params, headers):
        if url == UNITS_URL + "/query":
            assert params["where"] == "STATE='SC'"
            return {"features": [{"attributes": u} for u in UNITS]}
        return super().__call__(url, params, headers)


UNITS_URL = "https://example.test/arcgis/rest/services/SGMC/FeatureServer/7"


def test_units_table_join_adds_description_province_and_ref_id(tmp_path):
    sgmc.run(urls=[URL], state="SC", out_dir=tmp_path / "out", checkpoint_dir=tmp_path / "ckpt",
             fetch=OfficialServer(), log=lambda *_: None, units_tables={URL: UNITS_URL})
    data, meta = load(tmp_path)
    wando, granite = (f["properties"] for f in data["features"])
    assert wando["ref_id"] == "SC002" and wando["source_id"] == "usgs-sgmc:SC002"
    assert wando["province"] == "Coastal Plain"
    assert wando["unit_age"] == "Pleistocene"
    assert wando["description"] == "Clayey sand and clay, back-barrier"
    assert wando["strat_unit"] == "Wando Formation"
    assert "strat_unit" not in granite  # empty values are dropped
    assert meta["references"]["SC001"].startswith("Preliminary Geologic Map")
