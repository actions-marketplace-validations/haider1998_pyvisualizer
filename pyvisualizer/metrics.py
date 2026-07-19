"""
Architecture health metrics and dead-code detection.

The health score turns the graph into a single A–F grade the whole org can see
and defend — the gamification hook. It is computed deterministically from
structural properties (coupling, cycles, hub risk, orphans, ambiguity) so the
same code always yields the same grade, and PR diffs can report grade movement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Set

import networkx as nx

from pyvisualizer.core.model import CONFIDENCE_AMBIGUOUS

# Decorators that mark framework-registered entry points (called externally).
_ENTRY_DECORATOR = re.compile(
    r"(route|get|post|put|patch|delete|task|command|cli|fixture|"
    r"app\.|router\.|celery|click|api\.|websocket|on_event|handler|listener)",
    re.IGNORECASE,
)
_ENTRY_NAMES = {"main", "__main__", "run", "cli"}
_GOD_DEGREE = 20


@dataclass
class HealthReport:
    score: int
    grade: str
    components: Dict[str, int] = field(default_factory=dict)
    god_nodes: List[str] = field(default_factory=list)
    num_cycles: int = 0
    orphan_count: int = 0
    cross_module_ratio: float = 0.0
    ambiguous_ratio: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "components": self.components,
            "god_nodes": self.god_nodes,
            "num_cycles": self.num_cycles,
            "orphan_count": self.orphan_count,
            "cross_module_ratio": round(self.cross_module_ratio, 3),
            "ambiguous_ratio": round(self.ambiguous_ratio, 3),
        }


def _grade(score: int) -> str:
    table = [
        (97, "A+"),
        (93, "A"),
        (90, "A-"),
        (87, "B+"),
        (83, "B"),
        (80, "B-"),
        (77, "C+"),
        (73, "C"),
        (70, "C-"),
        (67, "D+"),
        (63, "D"),
        (60, "D-"),
    ]
    for threshold, letter in table:
        if score >= threshold:
            return letter
    return "F"


def _is_entry_point(node: str, data: Dict) -> bool:
    name = data.get("name", node.split(".")[-1])
    if name in _ENTRY_NAMES:
        return True
    if name.startswith("__") and name.endswith("__"):
        return True  # dunders are called implicitly
    for dec in data.get("decorator_names", []) or data.get("decorators", []):
        dec_name = dec if isinstance(dec, str) else dec.get("name", "")
        if _ENTRY_DECORATOR.search(dec_name or ""):
            return True
    return False


def compute_health(G: nx.DiGraph) -> HealthReport:
    """Compute a deterministic architecture health report for ``G``."""
    n = G.number_of_nodes()
    e = G.number_of_edges()
    if n == 0:
        return HealthReport(score=100, grade="A+", components={})

    # Coupling: fraction of edges that cross module boundaries.
    cross = 0
    ambiguous = 0
    for s, t, d in G.edges(data=True):
        if G.nodes[s].get("module") != G.nodes[t].get("module"):
            cross += 1
        if d.get("confidence") == CONFIDENCE_AMBIGUOUS:
            ambiguous += 1
    cross_ratio = cross / e if e else 0.0
    amb_ratio = ambiguous / e if e else 0.0

    # Cycles.
    try:
        num_cycles = sum(1 for c in nx.simple_cycles(G) if len(c) >= 2)
    except Exception:
        num_cycles = 0

    # God nodes: unusually high total degree (hub risk).
    god_nodes = sorted(
        node for node in G.nodes() if (G.in_degree(node) + G.out_degree(node)) >= _GOD_DEGREE
    )

    # Orphans: no calls in or out, and not a plausible entry point.
    orphans = [
        node
        for node in G.nodes()
        if G.in_degree(node) == 0
        and G.out_degree(node) == 0
        and not _is_entry_point(node, G.nodes[node])
    ]
    orphan_ratio = len(orphans) / n

    # Penalties (each capped) subtracted from a perfect 100.
    p_coupling = min(25, round(cross_ratio * 40))
    p_cycles = min(30, num_cycles * 6)
    p_god = min(20, len(god_nodes) * 5)
    p_orphan = min(15, round(orphan_ratio * 30))
    p_amb = min(10, round(amb_ratio * 20))

    score = max(0, 100 - (p_coupling + p_cycles + p_god + p_orphan + p_amb))
    return HealthReport(
        score=score,
        grade=_grade(score),
        components={
            "coupling": -p_coupling,
            "cycles": -p_cycles,
            "hub_risk": -p_god,
            "orphans": -p_orphan,
            "ambiguity": -p_amb,
        },
        god_nodes=god_nodes,
        num_cycles=num_cycles,
        orphan_count=len(orphans),
        cross_module_ratio=cross_ratio,
        ambiguous_ratio=amb_ratio,
    )


def find_dead_code(G: nx.DiGraph) -> List[str]:
    """Return functions unreachable from any detected entry point.

    Conservative: a node is reported only if it has zero callers *and* is not a
    plausible entry point (dunder, ``main``, or framework-decorated). Such nodes
    may still be public API called from outside the analyzed tree, so callers
    should treat this as a review list, not a delete list.
    """
    entry_points: Set[str] = {node for node in G.nodes() if _is_entry_point(node, G.nodes[node])}
    # Anything with callers is reachable in principle.
    reachable: Set[str] = set(entry_points)
    for ep in entry_points:
        reachable |= nx.descendants(G, ep)

    dead = [
        node
        for node in G.nodes()
        if node not in reachable
        and G.in_degree(node) == 0
        and not _is_entry_point(node, G.nodes[node])
    ]
    return sorted(dead)


def render_health(report: HealthReport, project_name: str = "") -> str:
    """Human-readable health scorecard."""
    lines = [
        f"Architecture Health: {report.grade}  ({report.score}/100)"
        + (f"  — {project_name}" if project_name else ""),
        "",
        "Component penalties:",
    ]
    for k, v in report.components.items():
        lines.append(f"    {k:<10} {v:+d}")
    lines.append("")
    lines.append(
        f"Cycles: {report.num_cycles} · God-nodes: {len(report.god_nodes)} "
        f"· Orphans: {report.orphan_count} "
        f"· Cross-module: {report.cross_module_ratio:.0%}"
    )
    if report.god_nodes:
        lines.append("High-risk hubs:")
        for g in report.god_nodes[:10]:
            lines.append(f"    ⚠ {g}")
    return "\n".join(lines)


_BADGE_COLORS = {
    "A": "#3fb950",
    "B": "#2f81f7",
    "C": "#d29922",
    "D": "#db6d28",
    "F": "#f85149",
}


def badge_svg(report: HealthReport) -> str:
    """A self-contained SVG badge (no shields.io / network dependency)."""
    letter = report.grade[0]
    color = _BADGE_COLORS.get(letter, "#8b949e")
    label = "architecture"
    value = f"{report.grade} · {report.score}"
    lw, vw = 74, 58
    total = lw + vw
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" '
        f'role="img" aria-label="{label}: {value}">'
        f'<rect width="{lw}" height="20" fill="#555"/>'
        f'<rect x="{lw}" width="{vw}" height="20" fill="{color}"/>'
        f'<g fill="#fff" font-family="Verdana,sans-serif" font-size="11">'
        f'<text x="6" y="14">{label}</text>'
        f'<text x="{lw + 6}" y="14">{value}</text>'
        f"</g></svg>"
    )
