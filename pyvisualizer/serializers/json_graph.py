"""
Canonical JSON serialization of the call graph.

This is the portable, diffable, machine-readable ground-truth artifact:
the substrate for ``diff``, ``check``, ``impact``, AI export, and the HTML
viewer. Output is deterministic (sorted, relative paths) so two runs on the
same code produce byte-identical JSON.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import networkx as nx

from pyvisualizer.core.model import (
    CONFIDENCE_AMBIGUOUS,
    KIND_ASYNC,
    KIND_CLASSMETHOD,
    KIND_CONSTRUCTOR,
    KIND_FUNCTION,
    KIND_METHOD,
    KIND_PROPERTY,
    KIND_STATICMETHOD,
)

#: Bump the minor when adding fields, the major on any breaking change.
SCHEMA_ID = "pyvisualizer/graph@1"


def _rel(path: str, root: Optional[str]) -> str:
    if not path:
        return ""
    if not root:
        return path
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path


def _node_kind(data: Dict[str, Any]) -> str:
    name = data.get("name", "")
    if name in ("__init__", "__new__"):
        return KIND_CONSTRUCTOR
    if data.get("is_property"):
        return KIND_PROPERTY
    if data.get("is_static"):
        return KIND_STATICMETHOD
    if data.get("is_classmethod"):
        return KIND_CLASSMETHOD
    if data.get("is_async"):
        return KIND_ASYNC
    if data.get("is_method"):
        return KIND_METHOD
    return KIND_FUNCTION


def _is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def graph_to_dict(
    G: nx.DiGraph,
    *,
    project_name: str = "",
    project_root: Optional[str] = None,
    tool_version: str = "",
) -> Dict[str, Any]:
    """Convert a call graph to the canonical, deterministic dict form."""
    nodes: List[Dict[str, Any]] = []
    for node in sorted(G.nodes()):
        d = G.nodes[node]
        name = d.get("name", node.split(".")[-1])
        nodes.append(
            {
                "id": node,
                "name": name,
                "module": d.get("module", ""),
                "class": d.get("class"),
                "file": _rel(d.get("path", ""), project_root),
                "lineno": d.get("lineno", 0),
                "end_lineno": d.get("end_lineno"),
                "kind": _node_kind(d),
                "is_async": bool(d.get("is_async", False)),
                "is_property": bool(d.get("is_property", False)),
                "is_static": bool(d.get("is_static", False)),
                "is_classmethod": bool(d.get("is_classmethod", False)),
                "is_method": bool(d.get("is_method", False)),
                "is_nested": bool(d.get("is_nested", False)),
                "is_private": _is_private(name),
                "decorators": list(d.get("decorator_names", [])),
                "args": list(d.get("args", [])),
                **({"churn": d["churn"]} if "churn" in d else {}),
            }
        )

    edges: List[Dict[str, Any]] = []
    cycles = 0
    ambiguous = 0
    for s, t in sorted(G.edges()):
        d = G.edges[s, t]
        is_cycle = bool(d.get("is_cycle", False))
        conf = d.get("confidence", "resolved")
        if is_cycle:
            cycles += 1
        if conf == CONFIDENCE_AMBIGUOUS:
            ambiguous += 1
        lineno = d.get("lineno", 0)
        file_rel = _rel(d.get("file", ""), project_root)
        edges.append(
            {
                "caller": s,
                "callee": t,
                "lineno": lineno,
                "file": file_rel,
                "provenance": f"{file_rel}:{lineno}" if file_rel else str(lineno),
                "confidence": conf,
                "via": d.get("via", ""),
                "candidates": list(d.get("candidates", [])),
                "is_cycle": is_cycle,
            }
        )

    out: Dict[str, Any] = {
        "schema": SCHEMA_ID,
        "generated_with": "py-code-visualizer",
        "tool_version": tool_version,
        "project": project_name,
    }
    # Optional repo block: when the project has a detectable git remote, every
    # file:line can become a clickable web link (blob/HEAD, never a SHA, so the
    # output stays deterministic). Absent when there is no remote — nothing else
    # depends on its presence.
    repo_url = _detect_repo_url(project_root)
    if repo_url:
        out["repo"] = {"url": repo_url, "link_ref": "HEAD"}
    out["stats"] = {
        "nodes": len(nodes),
        "edges": len(edges),
        "cycles": cycles,
        "ambiguous_edges": ambiguous,
    }
    out["nodes"] = nodes
    out["edges"] = edges
    return out


def _detect_repo_url(project_root: Optional[str]) -> str:
    if not project_root:
        return ""
    try:
        from pyvisualizer.changes import repo_web_url

        return repo_web_url(project_root)
    except Exception:  # pragma: no cover - defensive
        return ""


def graph_to_json(
    G: nx.DiGraph,
    *,
    project_name: str = "",
    project_root: Optional[str] = None,
    tool_version: str = "",
    indent: int = 2,
) -> str:
    """Serialize a call graph to a deterministic JSON string."""
    data = graph_to_dict(
        G,
        project_name=project_name,
        project_root=project_root,
        tool_version=tool_version,
    )
    return json.dumps(data, indent=indent, sort_keys=False, ensure_ascii=False)


def load_graph_json(path: str) -> Dict[str, Any]:
    """Load a previously serialized graph JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)
    return data
