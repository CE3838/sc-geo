"""Jobs that install the Playwright browser run on a pinned Ubuntu image.

Playwright installs Chromium only on the Ubuntu releases it supports, so a job
that runs `playwright install` must not follow `ubuntu-latest` to a newer image.
"""
import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
SUPPORTED = {"ubuntu-22.04", "ubuntu-24.04"}


def _jobs(text: str) -> dict[str, str]:
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"\n  ([A-Za-z0-9_-]+):\n", "\n" + body)
    return dict(zip(parts[1::2], parts[2::2]))


def test_playwright_jobs_use_a_pinned_supported_runner():
    found = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for name, job in _jobs(path.read_text()).items():
            if "playwright install" not in job:
                continue
            found += 1
            runner = re.search(r"runs-on:\s*(\S+)", job).group(1)
            assert runner in SUPPORTED, f"{path.name}:{name} runs Playwright on {runner}"
    assert found, "no workflow job installs Playwright"
