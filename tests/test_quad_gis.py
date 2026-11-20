import json

from harvest import quad_gis

FTP = "ftp://ftpdata.dnr.sc.gov/gisdata/glc/"


def rec(id_, scale=24000, year=2005, quads=("ROCKVILLE",), publisher="South Carolina Geological Survey", **avail):
    a = {"online": True, "gis": False, "gems_download": None, "gis_download": None, "pdf": [], "doi": None,
         "scgs_ftp": []}
    a.update(avail)
    return {"id": id_, "title": f"Geologic map of the {quads[0].title() if quads else 'X'} quadrangle",
            "year": year, "scale": scale, "publisher": publisher, "quadrangles": list(quads), "availability": a,
            "ngmdb_url": f"https://ngmdb.usgs.gov/Prodesc/proddesc_{id_.split(':')[-1]}.htm", "status": "published",
            "kind": "map"}


CATALOG = [
    rec("ngmdb:1", gis=True, gems_download="https://ngmdb.usgs.gov/ngm-bin/gems_download.pl?id=1",
        publisher="U.S. Geological Survey"),
    rec("ngmdb:2", gis=True, scgs_ftp=[FTP + "rockv06glc_line.zip", FTP + "rockv06glc_poly.zip"]),
    rec("ngmdb:3", gis=True),  # listed as having GIS, no public link
    rec("ngmdb:4", pdf=["https://example.org/map4.pdf"]),
    rec("ngmdb:5"),  # online at NGMDB only
    rec("ngmdb:6", online=False),
    rec("ngmdb:7", scale=100000, gis=True, gems_download="https://x/gems"),  # not a quadrangle map
    rec("scgs-draft:BATES", scale=None, quads=(), scgs_ftp=[FTP + "bates08glc_poly.zip"]),
    rec("ngmdb:8", gis=True, gis_download="https://example.org/gis8.zip"),
    rec("ngmdb:9", gis=True),  # GIS that cannot be read here (see EXTRA)
]
EXTRA = [
    {"id": "ngmdb:9", "download": "https://example.org/x.gdb.zip", "skip": "file geodatabase only"},
    {"id": "ngmdb:10", "kind": "shapefile", "downloads": [FTP + "dale06glc_poly.zip"], "note": "FTP package"},
]


def by_id(out):
    return {r["id"]: r for r in out["records"]}


def test_quadrangle_maps_are_classified_by_what_is_published():
    out = quad_gis.build(CATALOG + [rec("ngmdb:10", quads=("DALE",))], EXTRA)
    r = by_id(out)
    assert "ngmdb:7" not in r  # 1:100,000
    assert r["ngmdb:1"]["format"] == "gems" and r["ngmdb:1"]["download"] == [
        "https://ngmdb.usgs.gov/ngm-bin/gems_download.pl?id=1"]
    assert r["ngmdb:2"]["format"] == "shapefile" and r["ngmdb:2"]["download"] == [FTP + "rockv06glc_poly.zip"]
    assert r["scgs-draft:BATES"]["format"] == "shapefile" and r["scgs-draft:BATES"]["scale_inferred"] is True
    assert r["ngmdb:8"]["format"] == "gis_download"
    assert r["ngmdb:10"]["format"] == "shapefile" and r["ngmdb:10"]["download"] == [FTP + "dale06glc_poly.zip"]
    assert r["ngmdb:3"]["format"] == "gis_listed_no_download" and r["ngmdb:3"]["download"] == []
    assert r["ngmdb:9"]["format"] == "gis_not_readable" and "geodatabase" in r["ngmdb:9"]["note"]
    assert r["ngmdb:4"]["format"] == "pdf_only" and r["ngmdb:4"]["download"] == ["https://example.org/map4.pdf"]
    assert r["ngmdb:5"]["format"] == "pdf_only" and r["ngmdb:5"]["download"] == []
    assert r["ngmdb:5"]["record_url"].startswith("https://ngmdb.usgs.gov/")
    assert r["ngmdb:6"]["format"] == "not_online"


def test_record_fields_and_terms():
    r = by_id(quad_gis.build(CATALOG, EXTRA))
    one = r["ngmdb:1"]
    assert one["quads"] == ["ROCKVILLE"] and one["year"] == 2005 and one["scale"] == 24000
    # Terms only where a rule states them; flagged inferred because the record does not.
    assert one["terms"] == {"value": "Public domain (U.S. Government work)", "inferred": True,
                            "basis": "U.S. Geological Survey publication"}
    assert r["ngmdb:2"]["terms"] is None  # not stated anywhere on disk
    assert r["scgs-draft:BATES"]["quads"] == []


def test_summary_counts_gis_and_pdf_only():
    out = quad_gis.build(CATALOG, EXTRA)
    s = out["summary"]
    assert s["total"] == len(out["records"])
    assert s["with_gis_download"] == 4  # gems, two shapefile, gis_download
    assert s["gis_without_public_download"] == 2
    assert s["pdf_only"] == 2 and s["not_online"] == 1
    assert out["requests_made"] == 0


def test_write_is_stable_and_offline(tmp_path):
    p1 = quad_gis.write(quad_gis.build(CATALOG, EXTRA), tmp_path / "quad_gis.json")
    first = p1.read_text()
    quad_gis.write(quad_gis.build(CATALOG, EXTRA), tmp_path / "quad_gis.json")
    assert p1.read_text() == first  # no timestamps: a rebuild with the same catalog changes nothing
    assert json.loads(first)["records"][0]["id"] == "ngmdb:1"
