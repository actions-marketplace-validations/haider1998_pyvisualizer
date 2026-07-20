"""
Blast-radius / impact analysis.

Answers "if I touch this function, what could break?" — the single line that
makes a PR reviewer refuse to merge without checking. Transitive callers are
the blast radius; transitive callees are the dependency footprint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

import networkx as nx


@dataclass
class ImpactResult:
    target: str
    found: bool
    direct_callers: List[str] = field(default_factory=list)
    direct_callees: List[str] = field(default_factory=list)
    transitive_callers: List[str] = field(default_factory=list)
    transitive_callees: List[str] = field(default_factory=list)
    modules_affected: List[str] = field(default_factory=list)

    @property
    def blast_radius(self) -> int:
        return len(self.transitive_callers)


def resolve_target(G: nx.DiGraph, target: str) -> Optional[str]:
    """Resolve a user-supplied target to a node id (exact or suffix match)."""
    if target in G:
        return target
    matches: List[str] = [n for n in G.nodes() if n.endswith("." + target) or n == target]
    if len(matches) == 1:
        return matches[0]
    # Prefer an exact short-name match if unique.
    short_matches: List[str] = [n for n in G.nodes() if n.split(".")[-1] == target]
    if len(short_matches) == 1:
        return short_matches[0]
    return None


def analyze_impact(G: nx.DiGraph, target: str) -> ImpactResult:
    node = resolve_target(G, target)
    if node is None:
        return ImpactResult(target=target, found=False)

    ancestors: Set[str] = nx.ancestors(G, node)
    descendants: Set[str] = nx.descendants(G, node)

    modules = {G.nodes[n].get("module", "") for n in ancestors | descendants | {node}}
    modules.discard("")

    return ImpactResult(
        target=node,
        found=True,
        direct_callers=sorted(G.predecessors(node)),
        direct_callees=sorted(G.successors(node)),
        transitive_callers=sorted(ancestors),
        transitive_callees=sorted(descendants),
        modules_affected=sorted(modules),
    )


def risk_line(result: ImpactResult) -> str:
    """One-line risk summary suitable for a PR comment."""
    if not result.found:
        return f"⚠️ `{result.target}` not found in the call graph."
    short = result.target.split(".")[-1]
    return (
        f"⚠️ Touching `{short}` affects **{result.blast_radius}** transitive "
        f"caller(s) across **{len(result.modules_affected)}** module(s)."
    )


def render_text(result: ImpactResult) -> str:
    if not result.found:
        return f"Target not found: {result.target}"
    lines = [
        f"Impact analysis for: {result.target}",
        risk_line(result),
        "",
        f"Direct callers ({len(result.direct_callers)}):",
    ]
    lines += [f"    ← {c}" for c in result.direct_callers] or ["    (none)"]
    lines.append(f"Direct callees ({len(result.direct_callees)}):")
    lines += [f"    → {c}" for c in result.direct_callees] or ["    (none)"]
    lines.append(f"Transitive blast radius: {result.blast_radius} caller(s)")
    lines.append(f"Modules affected: {', '.join(result.modules_affected) or '(none)'}")
    return "\n".join(lines)


def render_markdown(result: ImpactResult, G: nx.DiGraph, project_root: str) -> str:
    """PR-comment-ready blast radius, with clickable ``file:line`` references."""
    from pyvisualizer.changes import Linker

    if not result.found:
        return f"⚠️ `{result.target}` not found in the call graph."
    link = Linker(G, project_root, markdown=True)
    lines = [
        f"### 💥 Impact — {link.ref(result.target)}",
        "",
        risk_line(result),
        "",
        f"**Direct callers ({len(result.direct_callers)})**",
    ]
    lines += [f"- {link.ref(c)}" for c in result.direct_callers] or ["- (none)"]
    lines.append("")
    lines.append(f"**Direct callees ({len(result.direct_callees)})**")
    lines += [f"- {link.ref(c)}" for c in result.direct_callees] or ["- (none)"]
    lines.append("")
    lines.append(
        f"Modules affected: {', '.join(f'`{m}`' for m in result.modules_affected) or '(none)'}"
    )
    return "\n".join(lines)
