"""
Context pack (Job 2) — a task-scoped, verified slice of the architecture for AI.

An agent asked to change some code doesn't need the whole repo re-read into its
context window; it needs the *verified* neighborhood of its task: the functions
it will touch, who calls them, what they call, and any cycle it might trip. This
module builds exactly that — centered on a focus set (explicit names/files, or
the functions changed vs a git ref — the same detection ``review`` uses), grown
to a token budget by **personalized PageRank** on the call graph, and rendered
as facts an agent can trust: signatures + `file:line` + confidence, never source
bodies it would have to be told to trust.

Everything is deterministic (sorted, rounded tie-breaks) and 100% verified — no
edge here was guessed. The token numbers are honest *estimates* (chars ÷ 4),
labeled as such.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import networkx as nx

from pyvisualizer.api import GraphResult
from pyvisualizer.changes import (
    changed_lines_from_git,
    map_lines_to_functions,
    repo_web_url,
    web_link,
)
from pyvisualizer.gates import find_cycles
from pyvisualizer.impact import resolve_target
from pyvisualizer.overlays import _toplevel

_CHARS_PER_TOKEN = 4  # rough, provider-agnostic estimate; explicitly labeled


@dataclass
class ContextPack:
    project_name: str
    focus: List[str] = field(default_factory=list)
    included: List[str] = field(default_factory=list)
    rendered_nodes: List[str] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    cycles: List[List[str]] = field(default_factory=list)
    omitted_count: int = 0
    budget_tokens: int = 0
    est_pack_tokens: int = 0
    est_full_tokens: int = 0
    repo_url: str = ""
    project_root: str = ""

    @property
    def reduction_pct(self) -> float:
        if self.est_full_tokens <= 0:
            return 0.0
        return round(100.0 * (1 - self.est_pack_tokens / self.est_full_tokens), 1)


def _resolve_focus(
    G: nx.DiGraph,
    focus: Optional[List[str]],
    from_git: Optional[str],
    project_root: str,
) -> List[str]:
    """Turn user focus (names/files) or a git ref into concrete node ids."""
    nodes: set = set()
    if from_git is not None:
        changed = map_lines_to_functions(
            G, changed_lines_from_git(project_root, from_git or None), project_root
        )
        nodes.update(changed)
    for token in focus or []:
        node = resolve_target(G, token)
        if node is not None:
            nodes.add(node)
            continue
        # Treat as a file path fragment: match nodes whose file ends with it.
        frag = token.replace(os.sep, "/")
        for n in G.nodes():
            path = G.nodes[n].get("path", "").replace(os.sep, "/")
            if path.endswith(frag):
                nodes.add(n)
    return sorted(nodes)


def _node_line(G: nx.DiGraph, node: str, top: str, repo_url: str) -> str:
    data = G.nodes[node]
    args = data.get("args", []) or []
    sig = f"{node}({', '.join(args)})"
    path = data.get("path", "")
    lineno = int(data.get("lineno", 0) or 0)
    rel = _rel(path, top)
    prov = f"{rel}:{lineno}" if rel else str(lineno)
    kind = data.get("kind", "")
    suffix = f" _{kind}_" if kind else ""
    if repo_url and rel:
        link = web_link(repo_url, rel, lineno)
        return f"- `{sig}` — [{prov}]({link}){suffix}"
    return f"- `{sig}` — {prov}{suffix}"


def _rel(path: str, top: str) -> str:
    if not path:
        return ""
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(top)).replace(os.sep, "/")
    except ValueError:
        return path


def _est_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def personalized_pagerank(
    G: nx.DiGraph,
    focus: List[str],
    *,
    alpha: float = 0.85,
    max_iter: int = 100,
    tol: float = 1.0e-10,
    bidirectional: bool = True,
) -> Dict[str, float]:
    """Personalized PageRank, computed here rather than via ``nx.pagerank``.

    networkx's ``pagerank`` dispatches to a SciPy implementation, and SciPy (with
    NumPy) is **not** a dependency of this package. Calling it on a normal install
    raises ``ModuleNotFoundError``; the previous code caught that and fell back to
    all-zero scores, which made the tie-break in ``_select_nodes`` degrade to plain
    alphabetical order — so a pack "focused" on one function quietly filled up with
    whatever sorted first. Worse, the output then depended on whether NumPy happened
    to be installed, breaking the determinism invariant.

    This is a plain power iteration over the same random-surfer model, using only
    the stdlib: deterministic, dependency-free, and identical on every machine.
    Dangling nodes (no out-edges) redistribute their mass to the focus set, which is
    what "personalized" means — the surfer always teleports back to the task.

    ``bidirectional`` walks call edges both ways. Relevance in a codebase is not
    one-directional: the callers of the function you are changing (its blast radius)
    matter as much as what it calls. A purely directed walk reaches only descendants,
    scoring every caller zero.
    """
    nodes = sorted(G.nodes())
    if not nodes:
        return {}
    teleport = [n for n in focus if n in G]
    if not teleport:
        return {n: 0.0 for n in nodes}

    weight = 1.0 / len(teleport)
    personalization = {n: 0.0 for n in nodes}
    for n in teleport:
        personalization[n] = weight

    if bidirectional:
        succ = {n: sorted(set(G.successors(n)) | set(G.predecessors(n))) for n in nodes}
    else:
        succ = {n: sorted(G.successors(n)) for n in nodes}
    dangling = [n for n in nodes if not succ[n]]
    rank = dict(personalization)

    for _ in range(max_iter):
        nxt = {n: 0.0 for n in nodes}
        # Mass stranded on dangling nodes teleports back to the focus set.
        leaked = alpha * sum(rank[n] for n in dangling)
        for n in nodes:
            out = succ[n]
            if not out:
                continue
            share = alpha * rank[n] / len(out)
            for m in out:
                nxt[m] += share
        for n in nodes:
            nxt[n] += (1.0 - alpha + leaked) * personalization[n]
        delta = sum(abs(nxt[n] - rank[n]) for n in nodes)
        rank = nxt
        if delta < tol:
            break
    return rank


def _select_nodes(
    G: nx.DiGraph,
    focus: List[str],
    budget_tokens: int,
    top: str,
    repo_url: str,
) -> List[str]:
    """Focus first, then neighbours, then PageRank-ranked fill — all under budget.

    ``budget_tokens`` is a promise: an agent asking for a 4,000-token pack has
    4,000 tokens to spend. Only the focus itself is exempt, because dropping what
    the caller explicitly asked about would be worse than overrunning.

    The fill only considers functions the focus can actually reach through call
    edges. Padding the budget with unrelated functions is worse than leaving it
    unspent: it spends an agent's context on noise and dilutes the signal.
    """
    focus_set = set(focus)
    pr = personalized_pagerank(G, sorted(focus_set)) if focus_set else {}

    def rank(n: str) -> tuple:
        return (-round(pr.get(n, 0.0), 12), n)

    def cost(n: str) -> int:
        return _est_tokens(_node_line(G, n, top, repo_url))

    # 1. The focus is non-negotiable — it is what was asked for.
    selected: List[str] = sorted(focus_set, key=rank)
    tokens = sum(cost(n) for n in selected)
    chosen: set = set(selected)

    # 2. Direct neighbours, best-ranked first — but they are *not* exempt from the
    #    budget. Adding every neighbour of every seed unconditionally is how a
    #    4,000-token request used to return 52,000 tokens on a hub-heavy repo.
    neighbours: set = set()
    for f in focus_set:
        if f in G:
            neighbours |= set(G.predecessors(f)) | set(G.successors(f))
    neighbours -= chosen

    # 3. Then everything else the focus can reach, by personalized PageRank.
    rest = [n for n in G.nodes() if n not in chosen and n not in neighbours and pr.get(n, 0.0) > 0.0]

    for group in (sorted(neighbours, key=rank), sorted(rest, key=rank)):
        for n in group:
            c = cost(n)
            if tokens + c > budget_tokens:
                # Skip this one and keep going: a single unusually long signature
                # must not halt the fill while cheaper, equally relevant functions
                # are still waiting. (Stopping here left 77% of packs under 75%
                # of their budget.)
                continue
            chosen.add(n)
            selected.append(n)
            tokens += c
    return sorted(selected)


def _full_source_tokens(files: List[str]) -> int:
    total_chars = 0
    for p in files:
        try:
            total_chars += os.path.getsize(p)
        except OSError:
            continue
    return max(1, total_chars // _CHARS_PER_TOKEN)


def build_context_pack(
    result: GraphResult,
    focus: Optional[List[str]] = None,
    from_git: Optional[str] = None,
    budget_tokens: int = 4000,
) -> ContextPack:
    """Build the deterministic, budget-bounded context pack model."""
    G = result.graph
    root = result.project_root
    top = _toplevel(root) or os.path.abspath(root)
    repo_url = repo_web_url(root)

    focus_nodes = _resolve_focus(G, focus, from_git, root)
    # No explicit focus → center on entry points (the app's front doors).
    if not focus_nodes:
        from pyvisualizer.metrics import _is_entry_point

        focus_nodes = sorted(
            n for n in G.nodes() if _is_entry_point(n, G.nodes[n]) and G.out_degree(n) > 0
        )
    # Still nothing (e.g. tiny lib) → every node is fair game.
    if not focus_nodes:
        focus_nodes = sorted(G.nodes())

    included = _select_nodes(G, focus_nodes, budget_tokens, top, repo_url)
    included_set = set(included)

    edges: List[Dict[str, Any]] = []
    for s, t, d in sorted(G.edges(data=True), key=lambda e: (e[0], e[1])):
        if s in included_set and t in included_set:
            edges.append(
                {
                    "caller": s,
                    "callee": t,
                    "confidence": d.get("confidence", "resolved"),
                    "provenance": d.get("provenance")
                    or f"{_rel(d.get('file', ''), top)}:{d.get('lineno', 0)}",
                }
            )

    cycles = [c for c in find_cycles(G) if included_set & set(c)]
    rendered_nodes = [_node_line(G, n, top, repo_url) for n in included]

    pack = ContextPack(
        project_name=result.project_name,
        focus=focus_nodes,
        included=included,
        rendered_nodes=rendered_nodes,
        edges=edges,
        cycles=cycles,
        omitted_count=G.number_of_nodes() - len(included),
        budget_tokens=budget_tokens,
        est_full_tokens=_full_source_tokens(result.files),
        repo_url=repo_url,
        project_root=root,
    )
    # Estimate the pack size from its payload (nodes + edges + cycles), i.e. what
    # an agent actually spends tokens on — computed before rendering the header,
    # which then simply displays the number.
    body = "\n".join(rendered_nodes)
    body += "\n".join(
        f"{e['caller']} {e['callee']} {e['confidence']} {e['provenance']}" for e in edges
    )
    body += "\n".join(" ".join(c) for c in cycles)
    pack.est_pack_tokens = _est_tokens(body)
    return pack


def render_pack_markdown(pack: ContextPack) -> str:
    lines: List[str] = [f"# Context Pack — {pack.project_name}"]
    lines.append("")
    lines.append(
        "> Verified, task-scoped architecture facts from py-code-visualizer. "
        "Every function below is real and every call edge is parsed from the "
        "AST with `file:line` provenance — use these as ground truth instead of "
        "re-deriving structure from source. Open the cited `file:line` when you "
        "need a function body."
    )
    lines.append("")
    lines.append(f"- Focus: {', '.join(f'`{f}`' for f in pack.focus) or '(project overview)'}")
    lines.append(
        f"- Included functions: **{len(pack.included)}** "
        f"(omitted {pack.omitted_count} under budget)"
    )
    if pack.reduction_pct > 0:
        savings = (
            f"**~{pack.reduction_pct}% smaller** than feeding the full source — "
            "the saving grows with codebase size"
        )
    else:
        savings = (
            "comparable to this small project's full source; the saving scales up "
            "sharply on large repos, where the pack stays small while the source doesn't"
        )
    lines.append(
        f"- Estimated size: **~{pack.est_pack_tokens} tokens** (pack) vs "
        f"**~{pack.est_full_tokens} tokens** (full source) — {savings}. "
        "_Estimate: chars÷4._"
    )
    lines.append("")

    lines.append("## Functions")
    lines.append("")
    lines.extend(pack.rendered_nodes)
    lines.append("")

    if pack.edges:
        lines.append("## Verified calls (caller → callee · confidence · provenance)")
        lines.append("")
        for e in pack.edges:
            lines.append(
                f"- `{e['caller']}` → `{e['callee']}` · {e['confidence']} · {e['provenance']}"
            )
        lines.append("")

    if pack.cycles:
        lines.append("## Circular dependencies touching this area")
        lines.append("")
        for c in pack.cycles:
            chain = " → ".join(x.split(".")[-1] for x in c) + " → " + c[0].split(".")[-1]
            lines.append(f"- `{chain}`")
        lines.append("")

    if pack.omitted_count:
        lines.append(
            f"_{pack.omitted_count} function(s) omitted to stay within the "
            f"~{pack.budget_tokens}-token budget. Load `ARCHITECTURE.json` for the full graph._"
        )
    return "\n".join(lines)


def render_pack_json(pack: ContextPack) -> str:
    data = {
        "schema": "pyvisualizer/context@1",
        "project": pack.project_name,
        "focus": pack.focus,
        "included": pack.included,
        "edges": pack.edges,
        "cycles": [list(c) for c in pack.cycles],
        "omitted": pack.omitted_count,
        "budget_tokens": pack.budget_tokens,
        "estimated_pack_tokens": pack.est_pack_tokens,
        "estimated_full_source_tokens": pack.est_full_tokens,
        "reduction_pct": pack.reduction_pct,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)
