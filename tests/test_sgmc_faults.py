"""Faults and other structure lines from the SGMC_Structure layer (harvest/sgmc.py)."""

import json

import pytest

from harvest import sgmc

URL = "https://example.test/arcgis/rest/services/SGMC/FeatureServer/1"
REF = "Horton, J.Wright, and Dicken, Connie L., 2001, Preliminary Geologic Map of the Appalachian Piedmont"

RULES = ["Undefined", "Fault, unknown type, certain", "Fault, unknown type, approximate",
         "Thrust fault, concealed (teeth on right from origin)", "Shear zone",
         "Fault, unknown type, inferred or queried", "Anticline, certain"]
LAYER = {
    "name": "SGMC_Structure",
    "objectIdField": "OBJECTID",
    "maxRecordCount": 2,
    "fields": [{"name": n} for n in ["OBJECTID", "STATE", "DESCRIPTION", "MISC", "REFERENCE", "NGMDB1"]]
    + [{"name": "RuleID", "domain": {"type": "codedValue",
                                     "codedValues": [{"name": n, "code": i + 1} for i, n in enumerate(RULES)]}}],
}


def line(oid, description, rule, **extra):
    props = {"OBJECTID": oid, "STATE": "SC", "DESCRIPTION": description, "MISC": "", "REFERENCE": REF,
             "NGMDB1": "https://ngmdb.usgs.gov/Prodesc/proddesc_1.htm", "RuleID": rule, **extra}
    return {"type": "Feature", "id": oid, "properties": props,
            "geometry": {"type": "LineString", "coordinates": [[-81 + oid * 0.01, 34], [-81 + oid * 0.01, 34.1]]}}


FEATURES = [
    line(1, "Fault, sense of displacement unknown or undefined, certain", 2),
    line(2, "Thrust fault, direction of motion undefined, certain", 2),
    line(3, "Shear zone", 5),
    line(4, "Fault, approximately located", 3),
    line(5, "Fault, queried", 6),
]


class FakeServer:
    def __init__(self, features=FEATURES, fail_offsets=()):
        self.features, self.fail_offsets, self.calls = list(features), set(fail_offsets), []

    def __call__(self, url, params, headers):
        self.calls.append(dict(params))
        if url == URL:
            return LAYER
        assert url == URL + "/query" and params["where"] == "STATE='SC'"
        if params.get("returnCountOnly") == "true":
            return {"count": len(self.features)}
        off, n = int(params["resultOffset"]), int(params["resultRecordCount"])
        if off in self.fail_offsets:
            raise OSError("network down")
        return {"type": "FeatureCollection", "features": self.features[off:off + n]}


def harvest(tmp_path, server):
    sgmc.run_structure([URL], "SC", tmp_path / "out", tmp_path / "ckpt", fetch=server, log=lambda *_: None)
    return json.loads((tmp_path / "out" / "sgmc-faults-sc.geojson").read_text())


@pytest.mark.parametrize("description,rule,expected", [
    ("Fault, sense of displacement unknown or undefined, certain", "Fault, unknown type, certain",
     ("fault", "certain", False)),
    ("Thrust fault, direction of motion undefined, certain", "Fault, unknown type, certain",
     ("thrust fault", "certain", False)),
    ("Shear zone", "Shear zone", ("shear zone", "certain", False)),
    ("Fault", "Fault, unknown type, approximate", ("fault", "approximate", False)),
    ("Thrust fault", "Thrust fault, concealed (teeth on right from origin)", ("thrust fault", "concealed", False)),
    ("Fault", "Fault, unknown type, inferred or queried", ("fault", "inferred", True)),
    ("Fault, queried", None, ("fault", "certain", True)),
    ("Normal fault?", None, ("fault", "certain", True)),
    ("Anticline", "Anticline, certain", ("fold", "certain", False)),
    ("Contact, concealed", None, ("contact", "concealed", False)),
    (None, None, ("other", "certain", False)),
])
def test_structure_class(description, rule, expected):
    c = sgmc.structure_class(description, rule)
    assert (c["kind"], c["certainty"], c["queried"]) == expected


def test_writes_lines_with_classes_and_provenance(tmp_path):
    data = harvest(tmp_path, FakeServer())
    assert len(data["features"]) == 5
    p = data["features"][1]["properties"]
    assert p["kind"] == "thrust fault" and p["certainty"] == "certain" and p["queried"] is False
    assert p["description"].startswith("Thrust fault")
    assert p["rule"] == "Fault, unknown type, certain"
    assert p["ref"] == "R1"
    assert p["source_id"] == "usgs-sgmc:structure"
    assert p["locator"] == "SGMC_Structure OBJECTID=2"
    assert p["extraction_method"] == "gis_import" and p["confidence"] == 1.0
    assert p["classes_inferred"] is True  # kind / certainty / queried are read from text: inferred
    assert data["features"][3]["properties"]["certainty"] == "approximate"
    assert data["features"][4]["properties"]["queried"] is True
    meta = data["meta"]
    assert meta["source_id"] == "usgs-sgmc" and meta["layer"] == "SGMC_Structure"
    assert meta["references"] == {"R1": REF}
    assert meta["count"] == 5 and "retrieved_at" in meta


def test_structure_harvest_resumes_from_checkpoints(tmp_path):
    with pytest.raises(OSError):
        harvest(tmp_path, FakeServer(fail_offsets={2}))
    server = FakeServer()
    data = harvest(tmp_path, server)
    assert [c["resultOffset"] for c in server.calls if "resultOffset" in c] == ["2", "4"]
    assert len(data["features"]) == 5
    assert not any((tmp_path / "ckpt").rglob("page-*.json"))


def test_main_keeps_the_polygons_when_the_fault_harvest_fails(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sgmc, "run", lambda *a, **k: calls.append("polygons"))

    def broken(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(sgmc, "run_structure", broken)
    logged = []
    sgmc.harvest_all({"feature_services": ["x"], "structure_services": ["y"]}, "SC", tmp_path, tmp_path,
                     log=lambda *a: logged.append(" ".join(map(str, a))))
    assert calls == ["polygons"]
    assert any("faults not harvested" in line for line in logged)
