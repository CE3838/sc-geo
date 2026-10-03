"""Packs the public data into one zip for the desktop app and other users.

The package holds the merged geology (and the SGMC layer) built into
web/data/geology, the source catalog, the Geolex lexicon and the South
Carolina outline, plus a manifest with a SHA-256 for each file. Deploy
publishes it as a GitHub Release tagged data-YYYYMMDD-HHMM (UTC).

Run: python -m merge.package [--out sc-geo-data.zip]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (folder in the repo, folder in the package)
SOURCES = [
    ("web/data/geology", "data/geology"),
    ("data/catalog", "data/catalog"),
    ("data/lexicon", "data/lexicon"),
]
SINGLE_FILES = [("web/data/sc-region.geojson", "data/sc-region.geojson")]
SUFFIXES = {".json", ".geojson", ".md"}


def tag_for(when: str) -> str:
    t = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(timezone.utc)
    return t.strftime("data-%Y%m%d-%H%M")


def _files(root: Path):
    for src, dest in SOURCES:
        folder = root / src
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUFFIXES:
                yield path, f"{dest}/{path.relative_to(folder).as_posix()}"
    for src, dest in SINGLE_FILES:
        if (root / src).is_file():
            yield root / src, dest


def build(root: Path, out: Path, tag: str, commit: str) -> dict:
    root = Path(root)
    files = list(_files(root))
    names = {name for _, name in files}
    if "data/geology/merged-surficial.geojson" not in names:
        raise SystemExit("No merged geology in web/data/geology; run python -m merge.build first")
    manifest = {
        "tag": tag,
        "commit": commit,
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": "Public data only. Each geology record names its source; see data/geology/merged-sources.json.",
        "files": [],
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path, name in files:
            body = path.read_bytes()
            zf.writestr(name, body)
            manifest["files"].append({"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="sc-geo-data.zip")
    ap.add_argument("--tag", default=None, help="default: data-YYYYMMDD-HHMM for now (UTC)")
    args = ap.parse_args(argv)
    tag = args.tag or tag_for(datetime.now(timezone.utc).isoformat())
    manifest = build(ROOT, Path(args.out), tag, os.environ.get("GITHUB_SHA", ""))
    total = sum(f["bytes"] for f in manifest["files"])
    print(f"{tag}: {len(manifest['files'])} files, {total / 1e6:.1f} MB -> {args.out}")
    # For the workflow: the tag to publish.
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"tag={tag}\n")


if __name__ == "__main__":
    main()
