"""
Architecture gates — enforce layering rules at the call-graph level.

Stricter than import-based linters: an import can exist without being used,
but a *call edge* is a real runtime dependency. Rules are declared in
``[tool.pyvisualizer.rules]`` and enforced by ``py-code-visualizer check``.

A node belongs to layer ``L`` when ``L`` appears as a dotted component of its
module (``myapp.domain.user`` is in layer ``domain``). A rule ``A -> B`` is
violated by any call from a node in layer A to a node in layer B.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import networkx as nx

from pyvisualizer.config import Rules
from pyvisualizer.core.model import CONFIDENCE_AMBIGUOUS


@dataclass
class Violation:
    kind: str  # "layer" | "cycle"
    detail: str  # human-readable rule / cycle text
    caller: str = ""
    callee: str = ""
    file: str = ""
    lineno: int = 0

    @property
    def location(self) -> str:
        if self.file:
            return f"{self.file}:{self.lineno}"
        return str(self.lineno) if self.lineno else ""


def _node_layers(module: str, layers: List[str]) -> List[str]:
    parts = set(module.split("."))
    return [layer for layer in layers if layer in parts]


def _parse_forbid(rule: str) -> Optional[Tuple[str, str]]:
    for sep in ("->", "→"):
        if sep in rule:
            left, right = rule.split(sep, 1)
            return left.strip(), right.strip()
    return None


def check_layer_rules(G: nx.DiGraph, rules: Rules) -> List[Violation]:
    """Return violations of the ``forbid`` layering rules."""
    violations: List[Violation] = []
    if not rules.forbid:
        return violations

    parsed = [p for p in (_parse_forbid(r) for r in rules.forbid) if p]
    layers = rules.layers or sorted({name for pair in parsed for name in pair})

    for s, t, d in G.edges(data=True):
        if not rules.allow_ambiguous and d.get("confidence") == CONFIDENCE_AMBIGUOUS:
            continue
        s_layers = _node_layers(G.nodes[s].get("module", ""), layers)
        t_layers = _node_layers(G.nodes[t].get("module", ""), layers)
        for a, b in parsed:
            if a in s_layers and b in t_layers:
                violations.append(
                    Violation(
                        kind="layer",
                        detail=f"{a} -> {b}",
                        caller=s,
                        callee=t,
                        file=d.get("file", G.nodes[s].get("path", "")),
                        lineno=d.get("lineno", 0),
                    )
                )
    violations.sort(key=lambda v: (v.detail, v.caller, v.callee, v.lineno))
    return violations


def find_cycles(G: nx.DiGraph, *, ignore_ambiguous: bool = True) -> List[List[str]]:
    """Return elementary cycles (optionally ignoring ambiguous-only edges)."""
    if ignore_ambiguous:
        H = nx.DiGraph()
        H.add_nodes_from(G.nodes())
        for s, t, d in G.edges(data=True):
            if d.get("confidence") != CONFIDENCE_AMBIGUOUS:
                H.add_edge(s, t)
        source = H
    else:
        source = G

    cycles: List[List[str]] = []
    try:
        for cycle in nx.simple_cycles(source):
            if len(cycle) >= 2:
                cycles.append(cycle)
    except Exception:  # pragma: no cover - defensive
        pass
    cycles.sort(key=lambda c: (len(c), c))
    return cycles


def cycle_violations(G: nx.DiGraph) -> List[Violation]:
    out: List[Violation] = []
    for cycle in find_cycles(G):
        chain = " -> ".join(n.split(".")[-1] for n in cycle) + " -> " + cycle[0].split(".")[-1]
        out.append(Violation(kind="cycle", detail=chain))
    return out


def render_report(
    layer_v: List[Violation],
    cycle_v: List[Violation],
) -> str:
    """Human-readable check report."""
    lines: List[str] = []
    if not layer_v and not cycle_v:
        return "✅ Architecture check passed: no rule or cycle violations."

    if cycle_v:
        lines.append(f"🔴 {len(cycle_v)} circular dependency violation(s):")
        for v in cycle_v:
            lines.append(f"    cycle: {v.detail}")
        lines.append("")
    if layer_v:
        lines.append(f"🔴 {len(layer_v)} layering violation(s):")
        for v in layer_v:
            loc = f"  ({v.location})" if v.location else ""
            lines.append(f"    [{v.detail}] {v.caller} → {v.callee}{loc}")
    return "\n".join(lines)
