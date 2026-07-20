"""
Code-review report (Job 1) — turn a diff into a focused reviewer's map.

Given the working-tree changes against a base ref, this answers the three
questions a reviewer on a large repo actually has: *what functions changed,
what can those changes reach (the blast radius), and where exactly do I look?* —
with a clickable `file:line` on every reference and a focused Mermaid subgraph
that renders natively in a PR comment.

It is a **report, not a gate**: gating stays in ``check`` / ``diff``. The only
optional exit-code knob is ``--fail-above`` for teams that want a blast-radius
ceiling. Everything is deterministic and reuses the shared engine in
``changes.py`` (the same change detection ``context`` uses) and ``impact.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import networkx as nx

from pyvisualizer.changes import (
    Linker,
    changed_lines_from_git,
    map_lines_to_functions,
    resolve_base_ref,
)
from pyvisualizer.core.model import CONFIDENCE_AMBIGUOUS
from pyvisualizer.gates import find_cycles
from pyvisualizer.metrics import compute_health


@dataclass
class ReviewResult:
    base_ref: str
    changed: List[str] = field(default_factory=list)
    impacted_callers: List[str] = field(default_factory=list)
    modules_affected: List[str] = field(default_factory=list)
    hub_changes: List[str] = field(default_factory=list)
    cycle_changes: List[Tuple[str, ...]] = field(default_factory=list)
    ambiguous_edges: List[Tuple[str, str]] = field(default_factory=list)
    call_sites: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def blast_radius(self) -> int:
        return len(self.impacted_callers)


def analyze_review(
    G: nx.DiGraph,
    project_root: str,
    base_ref: Optional[str] = None,
) -> ReviewResult:
    """Compute the review report model from the graph and git changes."""
    resolved = resolve_base_ref(project_root, base_ref)
    changed = map_lines_to_functions(
        G, changed_lines_from_git(project_root, base_ref), project_root
    )
    result = ReviewResult(base_ref=resolved, changed=changed)
    if not changed:
        return result

    changed_set = set(changed)
    impacted: set = set()
    for node in changed:
        impacted |= nx.ancestors(G, node)
    impacted -= changed_set
    result.impacted_callers = sorted(impacted)

    modules = {G.nodes[n].get("module", "") for n in impacted}
    modules.discard("")
    result.modules_affected = sorted(modules)

    # Call sites to review: direct callers of each changed function.
    for node in changed:
        callers = sorted(G.predecessors(node))
        if callers:
            result.call_sites[node] = callers

    # Risk flags.
    health = compute_health(G)
    god = set(health.god_nodes)
    result.hub_changes = sorted(changed_set & god)

    for cycle in find_cycles(G):
        if changed_set & set(cycle):
            # Rotate to the lexicographically smallest node so the rendered
            # chain is identical run-to-run (simple_cycles' start node isn't).
            i = cycle.index(min(cycle))
            result.cycle_changes.append(tuple(cycle[i:] + cycle[:i]))
    result.cycle_changes.sort()

    amb: List[Tuple[str, str]] = []
    for s, t, d in G.edges(data=True):
        if d.get("confidence") == CONFIDENCE_AMBIGUOUS and (s in changed_set or t in changed_set):
            amb.append((s, t))
    result.ambiguous_edges = sorted(amb)

    return result


def focused_subgraph(G: nx.DiGraph, changed: List[str]) -> nx.DiGraph:
    """Changed nodes plus their direct neighbors — the review neighborhood."""
    keep: set = set(changed)
    for node in changed:
        keep |= set(G.predecessors(node))
        keep |= set(G.successors(node))
    return G.subgraph(keep).copy()


def render_markdown(result: ReviewResult, G: nx.DiGraph, project_root: str) -> str:
    from pyvisualizer.visualizers.mermaid import generate_github_mermaid

    link = Linker(G, project_root, markdown=True)
    base = result.base_ref or "the base branch"
    lines: List[str] = ["## 🔍 Architecture Review"]

    if not result.changed:
        lines.append("")
        lines.append(f"_No Python function changes detected against `{base}`._")
        return "\n".join(lines)

    lines.append("")
    lines.append(
        f"**{len(result.changed)}** function(s) changed vs `{base}` · "
        f"blast radius **{result.blast_radius}** caller(s) across "
        f"**{len(result.modules_affected)}** module(s)."
    )

    lines.append("")
    lines.append("### ✏️ What changed")
    lines.append("")
    for node in result.changed:
        lines.append(f"- {link.ref(node)}")

    if result.impacted_callers:
        lines.append("")
        lines.append("### 🎯 Impacted area — review these call sites")
        lines.append("")
        for node in result.changed:
            callers = result.call_sites.get(node)
            if callers:
                lines.append(f"- {link.ref(node)} is called by:")
                for c in callers:
                    lines.append(f"    - {link.ref(c)}")
        by_mod: Dict[str, int] = {}
        for n in result.impacted_callers:
            m = G.nodes[n].get("module", "")
            by_mod[m] = by_mod.get(m, 0) + 1
        lines.append("")
        lines.append(
            "Transitive callers by module: "
            + ", ".join(
                f"`{m}` ({c})" for m, c in sorted(by_mod.items(), key=lambda kv: (-kv[1], kv[0]))
            )
        )

    flags = _risk_lines(result, link)
    if flags:
        lines.append("")
        lines.append("### ⚠️ Risk flags")
        lines.append("")
        lines.extend(flags)

    sub = focused_subgraph(G, result.changed)
    if sub.number_of_nodes() > 1:
        lines.append("")
        lines.append("### 🗺️ Changed neighborhood")
        lines.append("")
        lines.append("```mermaid")
        lines.append(generate_github_mermaid(sub, detail="function"))
        lines.append("```")

    lines.append("")
    lines.append(
        "<sub>🔒 Deterministic, AST-verified — every reference is a real "
        "`file:line`. Generated by py-code-visualizer `review`.</sub>"
    )
    return "\n".join(lines)


def _risk_lines(result: ReviewResult, link: Linker) -> List[str]:
    out: List[str] = []
    for node in result.hub_changes:
        out.append(f"- 🕸️ **Hub touched:** {link.ref(node)} is a high-fan-in/out node.")
    for cycle in result.cycle_changes:
        chain = " → ".join(n.split(".")[-1] for n in cycle) + " → " + cycle[0].split(".")[-1]
        out.append(f"- 🔴 **Cycle involves a changed function:** `{chain}`")
    for s, t in result.ambiguous_edges:
        out.append(
            f"- ❓ **Ambiguous call near the change:** {link.ref(s)} → "
            f"`{t.split('.')[-1]}` (flagged, not guessed)."
        )
    return out


def render_text(result: ReviewResult, G: nx.DiGraph, project_root: str) -> str:
    link = Linker(G, project_root, markdown=False)
    base = result.base_ref or "the base branch"
    if not result.changed:
        return f"No Python function changes detected against {base}."

    lines = [
        f"Architecture Review — {len(result.changed)} changed function(s) vs {base}",
        f"Blast radius: {result.blast_radius} caller(s) across "
        f"{len(result.modules_affected)} module(s)",
        "",
        "Changed:",
    ]
    lines += [f"    {link.ref(n)}" for n in result.changed]
    if result.impacted_callers:
        lines.append("Review these call sites:")
        for node in result.changed:
            for c in result.call_sites.get(node, []):
                lines.append(f"    {link.ref(c)} -> {node.split('.')[-1]}")
    flags = _risk_lines(result, link)
    if flags:
        lines.append("Risk flags:")
        lines += [f"    {f.lstrip('- ')}" for f in flags]
    return "\n".join(lines)
