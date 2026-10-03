from pathlib import Path

from harvest import geolex

FIX = Path(__file__).parent / "fixtures" / "geolex"


def test_parse_listing_status_and_replacements():
    rows = geolex.parse_listing((FIX / "listing.html").read_text())
    by = {r["name"]: r for r in rows}
    assert list(by) == ["Beech Hill", "Berryville", "Bessemer", "Beverly"]
    assert by["Beech Hill"]["status"] == "current"
    assert by["Beech Hill"]["usage"] == ["Beech Hill Formation (SC*-subsurface)"]
    assert by["Beech Hill"]["url"] == "https://ngmdb.usgs.gov/Geolex/Units/BeechHill_359.html"
    assert by["Bessemer"]["status"] == "abandoned"
    assert by["Bessemer"]["replaced_by"] == "Battleground"
    assert by["Beverly"]["status"] == "abandoned"
    assert by["Beverly"]["replaced_by"] == "Caesars Head"
    assert "same as Caesars Head Granite" in by["Beverly"]["notes"][0]


def test_parse_unit_page():
    u = geolex.parse_unit((FIX / "unit_ashley.html").read_text())
    assert u["age"] == "early Tertiary (early Oligocene)*"
    assert u["usage"] == ["Ashley Formation of Cooper Group (SC*)", "Ashley Member of Cooper Formation (SC*)"]
    assert u["subunits"].startswith("FORMATION STATUS")
    assert "Givhans Ferry State Park" in u["type_locality"]
    assert u["province"] == "Atlantic Coast basin*"
    assert u["references"] == ["M. Tuomey, 1848", "Ward and others, 1979", "Weems and others, 2016"]


def test_records_carry_provenance():
    rows = geolex.parse_listing((FIX / "listing.html").read_text())
    rec = geolex.to_record(rows[0], geolex.parse_unit((FIX / "unit_ashley.html").read_text()), "2026-10-03T00:00:00+00:00")
    assert rec["source_id"] == "usgs-geolex"
    assert rec["locator"] == "BeechHill_359"
    assert rec["extraction_method"] == "catalog_import"
    assert rec["age_range_ma"] == [27.82, 33.9]
    assert rec["age_range_inferred"] is True
