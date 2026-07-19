"""
Architectural diff between two graph snapshots.

Given the canonical JSON of a base ref and a head ref, compute exactly what
changed at the *architecture* level -- new/removed functions and call edges,
and, most importantly, newly introduced circular dependencies. This is what
turns a PR comment from "3 files changed" into "you just created a cycle
between billing and auth."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Set, Tuple

import networkx as nx

Edge = Tuple[str, str]


def _graph_from_json(data: Dict[str, Any]) -> nx.DiGraph:
    G = nx.DiGraph()
    for node in data.get("nodes", []):
        G.add_node(node["id"], **node)
    for edge in data.get("edges", []):
        G.add_edge(edge["caller"], edge["callee"], **edge)
    return G


def _cycle_keys(G: nx.DiGraph) -> Set[Tuple[str, ...]]:
    """Return canonical keys for each elementary cycle (rotation-invariant)."""
    keys: Set[Tuple[str, ...]] = set()
    try:
        for cycle in nx.simple_cycles(G):
            if len(cycle) < 2:
                continue
            # Rotate so the lexicographically smallest node is first.
            i = cycle.index(min(cycle))
            rotated = tuple(cycle[i:] + cycle[:i])
            keys.add(rotated)
    except Exception:  # pragma: no cover - defensive
        pass
    return keys


@dataclass
class DiffResult:
    added_functions: List[str] = field(default_factory=list)
    removed_functions: List[str] = field(default_factory=list)
    added_edges: List[Edge] = field(default_factory=list)
    removed_edges: List[Edge] = field(default_factory=list)
    new_cycles: List[Tuple[str, ...]] = field(default_factory=list)
    resolved_cycles: List[Tuple[str, ...]] = field(default_factory=list)
    base_stats: Dict[str, int] = field(default_factory=dict)
    head_stats: Dict[str, int] = field(default_factory=dict)
    base_grade: str = ""
    head_grade: str = ""
    base_score: int = 0
    head_score: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_functions or self.removed_functions or self.added_edges or self.removed_edges
        )

    @property
    def coupling_delta(self) -> int:
        return self.head_stats.get("cross_module_edges", 0) - self.base_stats.get(
            "cross_module_edges", 0
        )


def _cross_module_edges(G: nx.DiGraph) -> int:
    count = 0
    for s, t in G.edges():
        sm = G.nodes[s].get("module", "")
        tm = G.nodes[t].get("module", "")
        if sm and tm and sm != tm:
            count += 1
    return count


def diff_graphs(base: Dict[str, Any], head: Dict[str, Any]) -> DiffResult:
    """Compute the architectural diff between base and head JSON snapshots."""
    from pyvisualizer.metrics import compute_health

    gb = _graph_from_json(base)
    gh = _graph_from_json(head)

    hb = compute_health(gb)
    hh = compute_health(gh)

    base_nodes: Set[str] = set(gb.nodes())
    head_nodes: Set[str] = set(gh.nodes())
    base_edges: Set[Edge] = set(gb.edges())
    head_edges: Set[Edge] = set(gh.edges())

    base_cycles = _cycle_keys(gb)
    head_cycles = _cycle_keys(gh)

    result = DiffResult(
        added_functions=sorted(head_nodes - base_nodes),
        removed_functions=sorted(base_nodes - head_nodes),
        added_edges=sorted(head_edges - base_edges),
        removed_edges=sorted(base_edges - head_edges),
        new_cycles=sorted(head_cycles - base_cycles),
        resolved_cycles=sorted(base_cycles - head_cycles),
        base_stats={
            "nodes": gb.number_of_nodes(),
            "edges": gb.number_of_edges(),
            "cross_module_edges": _cross_module_edges(gb),
        },
        head_stats={
            "nodes": gh.number_of_nodes(),
            "edges": gh.number_of_edges(),
            "cross_module_edges": _cross_module_edges(gh),
        },
        base_grade=hb.grade,
        head_grade=hh.grade,
        base_score=hb.score,
        head_score=hh.score,
    )
    return result


def _short(node: str) -> str:
    return node.split(".")[-1]


def render_change_mermaid(diff: DiffResult, max_edges: int = 25) -> str:
    """Render a small, GitHub-safe Mermaid of the changed neighborhood.

    Added edges are green, removed edges red (dashed). Node ids are stable
    hashes so the block is deterministic.
    """
    touched: List[str] = []
    seen: Set[str] = set()
    for s, t in diff.added_edges + diff.removed_edges:
        for n in (s, t):
            if n not in seen:
                seen.add(n)
                touched.append(n)

    ids: Dict[str, str] = {n: f"n{i}" for i, n in enumerate(sorted(touched))}
    lines = ["flowchart LR"]
    for n in sorted(touched):
        lines.append(f'    {ids[n]}["{_short(n)}"]')

    shown = 0
    added_set = set(diff.added_edges)
    for s, t in diff.added_edges:
        if shown >= max_edges:
            break
        lines.append(f"    {ids[s]} ==>|added| {ids[t]}")
        shown += 1
    for s, t in diff.removed_edges:
        if shown >= max_edges:
            break
        # Only draw removed edge if both endpoints still shown.
        if s in ids and t in ids and (s, t) not in added_set:
            lines.append(f"    {ids[s]} -.->|removed| {ids[t]}")
            shown += 1

    lines.append("    classDef added fill:#e6ffed,stroke:#2ea043,color:#0b3d1a;")
    lines.append("    classDef removed fill:#ffebe9,stroke:#cf222e,color:#5c0d10;")
    return "\n".join(lines)


def render_markdown(
    diff: DiffResult,
    project_name: str = "",
    *,
    include_diagram: bool = True,
) -> str:
    """Render the diff as a Markdown PR-comment body."""
    md: List[str] = []
    title = "## 🗺️ Architecture Change Report"
    if project_name:
        title += f" — {project_name}"
    md.append(title)
    md.append("")

    # Health movement headline — teams defend a public grade.
    if diff.base_grade or diff.head_grade:
        if diff.head_score > diff.base_score:
            arrow = "📈"
        elif diff.head_score < diff.base_score:
            arrow = "📉"
        else:
            arrow = "➡️"
        md.append(
            f"**Architecture Health:** {diff.base_grade} → "
            f"{diff.head_grade} {arrow} "
            f"({diff.base_score} → {diff.head_score})"
        )
        md.append("")

    if not diff.has_changes:
        md.append("_No structural changes to the call graph in this change._")
        return "\n".join(md)

    # Headline: cycles first, they are the scariest.
    if diff.new_cycles:
        md.append("### 🔴 New circular dependencies")
        md.append("")
        for cycle in diff.new_cycles:
            chain = " → ".join(_short(n) for n in cycle) + " → " + _short(cycle[0])
            md.append(f"- `{chain}`")
        md.append("")
    if diff.resolved_cycles:
        md.append(f"### 🟢 Resolved {len(diff.resolved_cycles)} cycle(s)")
        md.append("")

    # Summary table.
    b, h = diff.base_stats, diff.head_stats
    md.append("| Metric | Base | Head | Δ |")
    md.append("|---|---:|---:|---:|")
    for label, key in [
        ("Functions", "nodes"),
        ("Call edges", "edges"),
        ("Cross-module edges", "cross_module_edges"),
    ]:
        bv, hv = b.get(key, 0), h.get(key, 0)
        delta = hv - bv
        sign = f"+{delta}" if delta > 0 else str(delta)
        md.append(f"| {label} | {bv} | {hv} | {sign} |")
    md.append("")

    def _list_section(title: str, items: List[Any], fmt: Callable[[Any], str]) -> None:
        if not items:
            return
        md.append(f"### {title} ({len(items)})")
        md.append("")
        for it in items[:15]:
            md.append(f"- {fmt(it)}")
        if len(items) > 15:
            md.append(f"- … and {len(items) - 15} more")
        md.append("")

    _list_section("➕ Added functions", diff.added_functions, lambda n: f"`{n}`")
    _list_section("➖ Removed functions", diff.removed_functions, lambda n: f"`{n}`")
    _list_section(
        "🔗 Added calls", diff.added_edges, lambda e: f"`{_short(e[0])}` → `{_short(e[1])}`"
    )
    _list_section(
        "✂️ Removed calls", diff.removed_edges, lambda e: f"`{_short(e[0])}` → `{_short(e[1])}`"
    )

    if include_diagram and (diff.added_edges or diff.removed_edges):
        md.append("### Changed neighborhood")
        md.append("")
        md.append("```mermaid")
        md.append(render_change_mermaid(diff))
        md.append("```")
        md.append("")

    md.append("---")
    md.append(
        "*Deterministic ground truth by "
        "[py-code-visualizer](https://github.com/haider1998/PyVisualizer) — "
        "every edge traceable to a line of code.*"
    )
    return "\n".join(md)
