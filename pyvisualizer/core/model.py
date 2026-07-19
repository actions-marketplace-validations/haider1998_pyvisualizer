"""
Canonical data model for the PyVisualizer call graph.

These types are the single source of truth that every downstream feature
(JSON export, diffing, gating, HTML/Mermaid rendering, AI export) reads from.

Design principle — *Ground Truth, never guesswork*:
    Every edge carries an explicit ``confidence`` and ``provenance`` (file:line).
    We never silently invent a relationship; when a call is ambiguous we say so
    and keep the full candidate list rather than picking one and pretending.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Edge confidence levels
# ---------------------------------------------------------------------------
#: The call was resolved to exactly one definition through a concrete binding
#: (import, local scope, ``self``, a typed variable, an explicit class name).
CONFIDENCE_RESOLVED = "resolved"
#: The call was resolved through a base class via the computed MRO.
CONFIDENCE_INHERITED = "inherited"
#: Several definitions could match and we could not disambiguate. The full
#: candidate list is preserved. Ambiguous edges are rendered dashed and are
#: excluded from architecture gates by default.
CONFIDENCE_AMBIGUOUS = "ambiguous"

CONFIDENCE_ORDER = {
    CONFIDENCE_RESOLVED: 0,
    CONFIDENCE_INHERITED: 1,
    CONFIDENCE_AMBIGUOUS: 2,
}

# Node kinds
KIND_FUNCTION = "function"
KIND_METHOD = "method"
KIND_CONSTRUCTOR = "constructor"
KIND_PROPERTY = "property"
KIND_STATICMETHOD = "staticmethod"
KIND_CLASSMETHOD = "classmethod"
KIND_ASYNC = "async"


@dataclass
class FunctionNode:
    """A single callable definition (function, method, nested closure)."""

    qualified_name: str
    name: str
    module: str
    file: str
    lineno: int
    cls: Optional[str] = None
    end_lineno: Optional[int] = None
    is_async: bool = False
    is_property: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    is_method: bool = False
    is_nested: bool = False
    decorators: List[str] = field(default_factory=list)
    args: List[str] = field(default_factory=list)
    returns: Optional[str] = None

    @property
    def kind(self) -> str:
        if self.name in ("__init__", "__new__"):
            return KIND_CONSTRUCTOR
        if self.is_property:
            return KIND_PROPERTY
        if self.is_static:
            return KIND_STATICMETHOD
        if self.is_classmethod:
            return KIND_CLASSMETHOD
        if self.is_async:
            return KIND_ASYNC
        if self.is_method:
            return KIND_METHOD
        return KIND_FUNCTION

    @property
    def is_private(self) -> bool:
        n = self.name
        return n.startswith("_") and not (n.startswith("__") and n.endswith("__"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.qualified_name,
            "name": self.name,
            "module": self.module,
            "class": self.cls,
            "file": self.file,
            "lineno": self.lineno,
            "end_lineno": self.end_lineno,
            "kind": self.kind,
            "is_async": self.is_async,
            "is_property": self.is_property,
            "is_static": self.is_static,
            "is_classmethod": self.is_classmethod,
            "is_method": self.is_method,
            "is_nested": self.is_nested,
            "is_private": self.is_private,
            "decorators": list(self.decorators),
            "args": list(self.args),
            "returns": self.returns,
        }


@dataclass
class CallEdge:
    """A directed call relationship with provenance and confidence."""

    caller: str
    callee: str
    lineno: int
    file: str
    confidence: str = CONFIDENCE_RESOLVED
    via: str = ""
    candidates: List[str] = field(default_factory=list)
    is_cycle: bool = False

    @property
    def provenance(self) -> str:
        return f"{self.file}:{self.lineno}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "caller": self.caller,
            "callee": self.callee,
            "lineno": self.lineno,
            "file": self.file,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "via": self.via,
            "candidates": list(self.candidates),
            "is_cycle": self.is_cycle,
        }
