import json

from harvest import net


def test_contact_headers_with_and_without_email(monkeypatch):
    monkeypatch.delenv("CONTACT_EMAIL", raising=False)
    assert net.contact_headers() == {"User-Agent": "sc-geo-harvest/0.1 (+https://github.com/CE3838/sc-geo)"}
    monkeypatch.setenv("CONTACT_EMAIL", " someone@example.test ")
    ua = net.contact_headers("sc-geo-parcel-registry/0.1")["User-Agent"]
    assert ua == "sc-geo-parcel-registry/0.1 (+https://github.com/CE3838/sc-geo; someone@example.test)"


def test_sgmc_keeps_its_old_header_name(monkeypatch):
    from harvest import sgmc
    monkeypatch.delenv("CONTACT_EMAIL", raising=False)
    assert sgmc._contact_headers() == net.contact_headers()


def test_write_json_atomic_formats(tmp_path):
    data = {"a": [1, 2], "é": "ü"}
    compact = tmp_path / "sub" / "c.json"
    net.write_json_atomic(compact, data, separators=(",", ":"))
    assert compact.read_text() == '{"a":[1,2],"\\u00e9":"\\u00fc"}'
    pretty = tmp_path / "p.json"
    net.write_json_atomic(pretty, data, indent=2, ensure_ascii=False, newline=True)
    assert pretty.read_text() == json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    assert not list(tmp_path.rglob("*.tmp"))
