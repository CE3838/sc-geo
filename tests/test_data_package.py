import hashlib
import json
import zipfile

import pytest

from merge import package


def _tree(root):
    geo = root / "web" / "data" / "geology"
    geo.mkdir(parents=True)
    (geo / "merged-surficial.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    (geo / "merged-sources.json").write_text("[]")
    (root / "web" / "data" / "sc-region.geojson").write_text("{}")
    (root / "web" / "data" / "README.md").write_text("notes")
    for sub, name in (("catalog", "sc_catalog.json"), ("lexicon", "geolex_sc.json")):
        (root / "data" / sub).mkdir(parents=True)
        (root / "data" / sub / name).write_text("[]")
        (root / "data" / sub / "README.md").write_text("readme")
    return root


def test_tag_sorts_by_time():
    assert package.tag_for("2026-10-03T09:05:59Z") == "data-20261003-0905"
    assert package.tag_for("2026-10-03T09:05:59Z") < package.tag_for("2026-10-10T00:00:00Z")


def test_build_writes_data_entries_and_a_manifest(tmp_path):
    root = _tree(tmp_path / "repo")
    out = tmp_path / "sc-geo-data.zip"
    manifest = package.build(root, out, tag="data-20261003-0905", commit="abc123")
    with zipfile.ZipFile(out) as zf:
        names = sorted(zf.namelist())
        assert names == [
            "data/catalog/README.md",
            "data/catalog/sc_catalog.json",
            "data/geology/merged-sources.json",
            "data/geology/merged-surficial.geojson",
            "data/lexicon/README.md",
            "data/lexicon/geolex_sc.json",
            "data/sc-region.geojson",
            "manifest.json",
        ]
        stored = json.loads(zf.read("manifest.json"))
        body = zf.read("data/geology/merged-sources.json")
    assert stored == manifest
    assert manifest["tag"] == "data-20261003-0905"
    assert manifest["commit"] == "abc123"
    entry = next(f for f in manifest["files"] if f["path"] == "data/geology/merged-sources.json")
    assert entry == {"path": "data/geology/merged-sources.json", "bytes": len(body),
                     "sha256": hashlib.sha256(body).hexdigest()}


def test_build_refuses_a_package_without_merged_geology(tmp_path):
    root = _tree(tmp_path / "repo")
    (root / "web" / "data" / "geology" / "merged-surficial.geojson").unlink()
    with pytest.raises(SystemExit, match="merged geology"):
        package.build(root, tmp_path / "x.zip", tag="data-20261003-0905", commit="")


def test_build_never_packages_pdfs(tmp_path):
    root = _tree(tmp_path / "repo")
    (root / "data" / "catalog" / "scan.pdf").write_bytes(b"%PDF-1.4")
    out = tmp_path / "p.zip"
    package.build(root, out, tag="data-20261003-0905", commit="")
    with zipfile.ZipFile(out) as zf:
        assert not [n for n in zf.namelist() if n.lower().endswith(".pdf")]


def test_manifest_says_sources_are_cited_and_there_is_no_warranty(tmp_path):
    root = _tree(tmp_path / "repo")
    manifest = package.build(root, tmp_path / "p.zip", tag="data-20261003-0905", commit="")
    assert "without warranty" in manifest["notes"]
    assert "terms" in manifest["notes"]
