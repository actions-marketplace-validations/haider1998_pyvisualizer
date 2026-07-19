"""
Project configuration loaded from ``[tool.pyvisualizer]`` in pyproject.toml.

Lets a repo declare its defaults once so CI/pre-commit invocations are a single
flag-less command, e.g.::

    [tool.pyvisualizer]
    exclude = ["tests", "migrations"]
    max_nodes = 120
    target = "README.md"
    detail = "module"          # module | class | function

    [tool.pyvisualizer.rules]
    layers = ["api", "domain", "infra"]
    forbid = ["domain -> api", "domain -> infra"]
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pyvisualizer.config")

try:  # Python 3.11+
    import tomllib as _toml

    _TOML_MODE = "rb"
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    try:
        import tomli as _toml  # type: ignore

        _TOML_MODE = "rb"
    except ModuleNotFoundError:
        _toml = None  # type: ignore
        _TOML_MODE = "rb"


@dataclass
class Rules:
    """Architecture rules enforced by ``check``."""

    layers: List[str] = field(default_factory=list)
    forbid: List[str] = field(default_factory=list)
    allow_ambiguous: bool = False  # let ambiguous edges satisfy/violate rules

    @property
    def enabled(self) -> bool:
        return bool(self.forbid)


@dataclass
class Config:
    exclude: List[str] = field(default_factory=list)
    modules: List[str] = field(default_factory=list)
    max_nodes: int = 150
    target: str = "README.md"
    detail: str = "module"  # module | class | function
    strict: bool = False
    project_name: Optional[str] = None
    rules: Rules = field(default_factory=Rules)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        rules_data = data.get("rules", {}) or {}
        rules = Rules(
            layers=list(rules_data.get("layers", [])),
            forbid=list(rules_data.get("forbid", [])),
            allow_ambiguous=bool(rules_data.get("allow_ambiguous", False)),
        )
        return cls(
            exclude=list(data.get("exclude", [])),
            modules=list(data.get("modules", [])),
            max_nodes=int(data.get("max_nodes", 150)),
            target=str(data.get("target", "README.md")),
            detail=str(data.get("detail", "module")),
            strict=bool(data.get("strict", False)),
            project_name=data.get("project_name"),
            rules=rules,
        )


def find_pyproject(start: str) -> Optional[str]:
    """Walk upward from ``start`` to locate the nearest pyproject.toml."""
    cur = os.path.abspath(start if os.path.isdir(start) else os.path.dirname(start))
    while True:
        candidate = os.path.join(cur, "pyproject.toml")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def load_config(path: str) -> Config:
    """Load ``[tool.pyvisualizer]`` config relative to ``path`` (best effort)."""
    if _toml is None:
        logger.debug("No TOML parser available; using default config.")
        return Config()
    pyproject = find_pyproject(path)
    if not pyproject:
        return Config()
    try:
        with open(pyproject, _TOML_MODE) as f:
            data = _toml.load(f)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not parse %s: %s", pyproject, e)
        return Config()
    tool = data.get("tool", {}).get("pyvisualizer", {})
    return Config.from_dict(tool or {})
