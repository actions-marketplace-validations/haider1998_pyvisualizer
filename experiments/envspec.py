"""Per-instance environment specs, taken from SWE-bench's own harness.

Reproducing these environments by hand is guesswork: Flask 2.3 needs
``Werkzeug==2.3.7`` (3.x dropped ``werkzeug.__version__``), sklearn needs a pinned
NumPy, and so on. Getting it wrong makes a healthy checkout fail at import time,
which would show up as an "agent failure" and quietly corrupt the experiment.

So we don't guess: we read the pinned package lists straight from SWE-bench's
published ``constants/python.py``. The file is pure dict literals with no imports,
so it is fetched once, cached, and evaluated in an empty namespace.

Caveat, stated plainly: SWE-bench runs each spec's exact Python version inside
Docker. There is no Docker here and only one old interpreter available, so every
run uses that one. Instances whose environment refuses to build are dropped
before any agent runs — and the drop is recorded.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from experiments.dataset import CACHE_DIR, _fetch

_SPEC_URL = (
    "https://raw.githubusercontent.com/SWE-bench/SWE-bench/main/"
    "swebench/harness/constants/python.py"
)
_SPEC_CACHE = os.path.join(CACHE_DIR, "swebench_specs.py")

_MAP: Dict[str, Dict[str, Any]] = {}


def _load_map() -> Dict[str, Dict[str, Any]]:
    global _MAP
    if _MAP:
        return _MAP
    if not os.path.exists(_SPEC_CACHE):
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_SPEC_CACHE, "w", encoding="utf-8") as f:
            f.write(_fetch(_SPEC_URL))
    with open(_SPEC_CACHE, "r", encoding="utf-8") as f:
        source = f.read()
    namespace: Dict[str, Any] = {}
    exec(compile(source, _SPEC_CACHE, "exec"), namespace)  # noqa: S102 - literal dicts only
    _MAP = namespace["MAP_REPO_VERSION_TO_SPECS_PY"]
    return _MAP


def spec_for(repo: str, version: str) -> Dict[str, Any]:
    """The install spec for one instance, or {} when SWE-bench has none."""
    by_version = _load_map().get(repo, {})
    result: Dict[str, Any] = by_version.get(version, {})
    return result


def pip_packages(repo: str, version: str) -> List[str]:
    spec = spec_for(repo, version)
    pkgs = list(spec.get("pip_packages", []))
    # Every suite here is driven by pytest except django's own runner; SWE-bench
    # assumes it is present in the image rather than listing it.
    if repo != "django/django" and not any(p.lower().startswith("pytest") for p in pkgs):
        pkgs.append("pytest")
    return pkgs


def install_command(repo: str, version: str) -> str:
    spec = spec_for(repo, version)
    cmd: str = spec.get("install", "python -m pip install -e .")
    return cmd
