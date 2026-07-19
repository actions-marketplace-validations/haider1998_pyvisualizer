"""
High-level programmatic API.

A single entry point, :func:`build_graph`, that every CLI subcommand and every
integration (pre-commit, CI, MCP) builds on. Keeps discovery + analysis +
filtering in one deterministic place.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

import networkx as nx

from pyvisualizer.core.graph import build_call_graph
from pyvisualizer.core.model import CONFIDENCE_AMBIGUOUS
from pyvisualizer.core.resolver import filter_by_depth, filter_by_modules
from pyvisualizer.utils.file_discovery import (
    analyze_project,
    find_project_python_files,
)

logger = logging.getLogger("pyvisualizer.api")


@dataclass
class GraphResult:
    """The analyzed project graph plus the metadata downstream tools need."""

    graph: nx.DiGraph
    project_name: str
    project_root: str
    files: List[str] = field(default_factory=list)

    @property
    def num_nodes(self) -> int:
        return int(self.graph.number_of_nodes())

    @property
    def num_edges(self) -> int:
        return int(self.graph.number_of_edges())


def build_graph(
    path: str,
    *,
    modules: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    entry: Optional[str] = None,
    depth: Optional[int] = None,
    max_nodes: Optional[int] = None,
    strict: bool = False,
    project_name: Optional[str] = None,
) -> GraphResult:
    """Analyze ``path`` and return a filtered, deterministic call graph.

    Args:
        path: File or directory to analyze.
        modules: If given, keep only these module prefixes.
        exclude: Module prefixes to drop.
        entry / depth: Slice to ``depth`` calls around ``entry``.
        max_nodes: Trim to at most this many nodes (least-connected first).
        strict: Drop ``ambiguous`` edges entirely (no guesses at all).
        project_name: Override the inferred project name.
    """
    project_path = os.path.abspath(path)
    if not os.path.exists(project_path):
        raise FileNotFoundError(f"Path does not exist: {project_path}")

    name = project_name or os.path.basename(project_path.rstrip(os.sep))
    py_files = find_project_python_files(project_path)
    if not py_files:
        raise ValueError(f"No Python files found in {path}")

    project_root = project_path if os.path.isdir(project_path) else os.path.dirname(project_path)

    analyzers, calls = analyze_project(py_files, project_root)
    G = build_call_graph(analyzers, calls)
    logger.info(
        "Built graph with %d functions and %d calls", G.number_of_nodes(), G.number_of_edges()
    )

    if modules:
        G = filter_by_modules(G, modules)
    if exclude:
        to_remove = [
            n for n in G.nodes() if any(G.nodes[n].get("module", "").startswith(x) for x in exclude)
        ]
        G.remove_nodes_from(to_remove)
    if entry and depth:
        G = filter_by_depth(G, entry, depth)
    if strict:
        amb = [
            (s, t) for s, t, d in G.edges(data=True) if d.get("confidence") == CONFIDENCE_AMBIGUOUS
        ]
        G.remove_edges_from(amb)
    if max_nodes is not None and G.number_of_nodes() > max_nodes:
        # Deterministic trim: drop least-connected nodes, ties broken by name.
        ranked = sorted(G.degree(), key=lambda kv: (kv[1], kv[0]))
        drop = [n for n, _ in ranked[: G.number_of_nodes() - max_nodes]]
        G.remove_nodes_from(drop)

    return GraphResult(graph=G, project_name=name, project_root=project_root, files=py_files)
