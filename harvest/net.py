"""Helpers shared by the harvest jobs: the project User-Agent and atomic JSON writes.

The contact email (CONTACT_EMAIL) is read from the environment and only sent
in the User-Agent header; it is never printed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_URL = "https://github.com/CE3838/sc-geo"


def contact_headers(agent: str = "sc-geo-harvest/0.1") -> dict[str, str]:
    """User-Agent naming the project, plus the contact email when CONTACT_EMAIL is set."""
    email = os.environ.get("CONTACT_EMAIL", "").strip()
    return {"User-Agent": f"{agent} (+{REPO_URL}; {email})" if email else f"{agent} (+{REPO_URL})"}


def write_json_atomic(path: Path, data: Any, newline: bool = False, **dumps_kwargs: Any) -> None:
    """Write JSON through a temporary file and rename, so a stopped job never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, **dumps_kwargs) + ("\n" if newline else ""))
    tmp.replace(path)
