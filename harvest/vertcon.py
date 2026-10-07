"""Download the NGVD29-to-NAVD88 shift grid once (config/extract.json `vertical_datum`).

    python -m harvest.vertcon

One request, ever: the file goes to `grid_path` under .cache/ (never committed)
with a `<file>.json` note of its URL, sha256 and download time. When the file is
there, nothing is fetched; when `grid_sha256` is set, the file must match it. The
grid is a U.S. Government work (NOAA NGS VERTCON), public domain; cite NGS when
values converted with it are published.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
CONFIG: dict = json.loads((ROOT / "config" / "extract.json").read_text())["vertical_datum"]


class GridError(Exception):
    pass


def _fetch(url: str) -> bytes:
    agent = json.loads((ROOT / "config" / "extract.json").read_text())["user_agent"]
    req = urllib.request.Request(url, headers={"User-Agent": agent})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def grid_path(cfg: dict = CONFIG) -> Path:
    p = Path(cfg["grid_path"])
    return p if p.is_absolute() else ROOT / p


def ensure_grid(cfg: dict = CONFIG, fetch: Callable[[str], bytes] = _fetch) -> Path:
    path = grid_path(cfg)
    want = cfg.get("grid_sha256")
    if path.exists():
        if want and hashlib.sha256(path.read_bytes()).hexdigest() != want:
            raise GridError(f"{path} does not match grid_sha256; delete it to download again")
        return path
    body = fetch(cfg["grid_url"])
    sha = hashlib.sha256(body).hexdigest()
    if want and sha != want:
        raise GridError(f"downloaded grid sha256 {sha} does not match grid_sha256 {want}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(body)
    os.replace(tmp, path)
    path.with_suffix(path.suffix + ".json").write_text(json.dumps({
        "url": cfg["grid_url"], "sha256": sha, "bytes": len(body), "source": cfg.get("grid_source"),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=1))
    return path


def main() -> int:
    try:
        path = ensure_grid()
    except (GridError, OSError) as err:
        print(f"grid not available: {err}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
