"""Fetch and cache SWE-bench Verified — 500 human-validated real GitHub issues.

Deliberately stdlib-only: the Hugging Face rows API serves the dataset as plain
JSON, so we avoid pulling ``datasets``/``pyarrow`` (large, and irrelevant to the
thing being measured). Rows are cached on disk so the experiment is repeatable
offline and the numbers can't silently shift under us.

Every row carries its own ground truth:

* ``patch``        — the real fix that was merged (our localization oracle)
* ``test_patch``   — the tests that prove it (the answer key; agents never see it)
* ``FAIL_TO_PASS`` — must go fail → pass
* ``PASS_TO_PASS`` — must stay passing (regression guard)
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

DATASET = "princeton-nlp/SWE-bench_Verified"
_ROWS_API = "https://datasets-server.huggingface.co/rows"
_PAGE = 100

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_FILE = os.path.join(CACHE_DIR, "swebench_verified.json")

# Repos that are pure Python and install natively with `pip install -e .`.
# There is no Docker in this environment, so the agent track (which must run the
# real FAIL_TO_PASS / PASS_TO_PASS suites) is restricted to these. Excluded:
# scikit-learn, matplotlib, astropy, pydata/xarray's compiled deps — they need a
# C/C++ toolchain and pinned build environments to compile at an old commit.
PURE_PYTHON_REPOS = {
    "django/django",
    "sympy/sympy",
    "sphinx-doc/sphinx",
    "pylint-dev/pylint",
    "pytest-dev/pytest",
    "psf/requests",
    "pallets/flask",
    "mwaskom/seaborn",
}


def _fetch(url: str) -> str:
    """Fetch a URL as text.

    Prefers ``curl``: several Python builds (notably python.org macOS builds)
    ship without a usable root-certificate store, so ``urllib`` fails with
    CERTIFICATE_VERIFY_FAILED while curl — using the system store — works fine.
    """
    try:
        import shutil
        import subprocess

        if shutil.which("curl"):
            out = subprocess.run(
                ["curl", "-sS", "--fail", "--max-time", "90", url],
                capture_output=True,
                check=True,
            )
            return out.stdout.decode("utf-8")
    except Exception:
        pass  # fall through to urllib
    req = urllib.request.Request(url, headers={"User-Agent": "py-code-visualizer-exp"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return str(resp.read().decode("utf-8"))


def _get_json(url: str, *, retries: int = 4) -> Dict[str, Any]:
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            data: Dict[str, Any] = json.loads(_fetch(url))
            return data
        except Exception as e:  # network flake — back off and retry
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def download() -> List[Dict[str, Any]]:
    """Page through the rows API, verifying nothing was truncated."""
    rows: List[Dict[str, Any]] = []
    offset = 0
    total = None
    while total is None or offset < total:
        qs = urllib.parse.urlencode(
            {
                "dataset": DATASET,
                "config": "default",
                "split": "test",
                "offset": offset,
                "length": _PAGE,
            }
        )
        payload = _get_json(f"{_ROWS_API}?{qs}")
        total = int(payload["num_rows_total"])
        for item in payload["rows"]:
            # A truncated cell would silently corrupt the ground truth.
            if item.get("truncated_cells"):
                raise RuntimeError(
                    f"row {item['row'].get('instance_id')} truncated: {item['truncated_cells']}"
                )
            rows.append(item["row"])
        offset += _PAGE
    if len(rows) != total:
        raise RuntimeError(f"expected {total} rows, got {len(rows)}")
    return rows


def load(*, refresh: bool = False) -> List[Dict[str, Any]]:
    """Return the dataset, downloading once and caching it."""
    if not refresh and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cached: List[Dict[str, Any]] = json.load(f)
            return cached
    rows = download()
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    return rows


def parse_test_list(raw: str) -> List[str]:
    """FAIL_TO_PASS / PASS_TO_PASS arrive as a JSON-encoded list-in-a-string."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(x) for x in parsed] if isinstance(parsed, list) else []


if __name__ == "__main__":
    data = load()
    from collections import Counter

    print(f"{len(data)} instances cached at {CACHE_FILE}")
    print("\nby repo:")
    for repo, n in Counter(d["repo"] for d in data).most_common():
        mark = "pure-python" if repo in PURE_PYTHON_REPOS else "needs-compiler"
        print(f"  {n:4d}  {repo:28s} {mark}")
    print("\nby difficulty:")
    for diff, n in Counter(d.get("difficulty", "?") for d in data).most_common():
        print(f"  {n:4d}  {diff}")
