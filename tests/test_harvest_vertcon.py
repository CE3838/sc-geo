"""harvest/vertcon.py: the datum grid is downloaded once and never again."""

import hashlib
import json

import pytest

from harvest import vertcon

BODY = b"II*\0 fake grid bytes"


def cfg(tmp_path, sha=None):
    return {"grid_url": "https://example.test/us_noaa_vertcone.tif", "grid_path": str(tmp_path / "g" / "grid.tif"),
            "grid_sha256": sha}


def test_downloads_once_and_records_provenance(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return BODY

    c = cfg(tmp_path)
    path = vertcon.ensure_grid(c, fetch=fetch)
    assert path.read_bytes() == BODY and calls == [c["grid_url"]]
    meta = json.loads(path.with_suffix(".tif.json").read_text())
    assert meta["url"] == c["grid_url"] and meta["sha256"] == hashlib.sha256(BODY).hexdigest() and meta["fetched_at"]
    assert vertcon.ensure_grid(c, fetch=fetch) == path
    assert len(calls) == 1  # never re-downloaded


def test_checksum_mismatch_keeps_nothing(tmp_path):
    c = cfg(tmp_path, sha="0" * 64)
    with pytest.raises(vertcon.GridError, match="sha256"):
        vertcon.ensure_grid(c, fetch=lambda url: BODY)
    assert not (tmp_path / "g" / "grid.tif").exists()


def test_existing_file_with_wrong_checksum_is_reported_not_refetched(tmp_path):
    c = cfg(tmp_path, sha="0" * 64)
    p = tmp_path / "g" / "grid.tif"
    p.parent.mkdir(parents=True)
    p.write_bytes(BODY)
    with pytest.raises(vertcon.GridError, match="sha256"):
        vertcon.ensure_grid(c, fetch=lambda url: pytest.fail("must not download again"))


def test_config_names_an_official_grid_and_a_cache_path():
    v = vertcon.CONFIG
    assert v["grid_url"].startswith("https://") and v["grid_path"].startswith(".cache/")
    assert "VERTCON" in v["grid_source"] and v["msl_as_ngvd29_before"] == 1991
