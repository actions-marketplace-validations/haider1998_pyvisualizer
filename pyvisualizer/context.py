"""
Context pack (Job 2) — a task-scoped, verified slice of the architecture for AI.

An agent asked to change some code doesn't need the whole repo re-read into its
context window; it needs the *verified* neighborhood of its task: the functions
it will touch, who calls them, what they call, and any cycle it might trip. This
module builds exactly that — centered on a focus set (explicit names/files, the
functions changed vs a git ref, or seeds derived from a prose ``--task``
description via lexical retrieval), grown to a token budget by **personalized
PageRank** on the call graph. The pack renders signatures + `file:line` +
confidence for everything it includes, plus full source bodies for the
top-ranked functions while the budget allows — the structure is verified ground
truth; anything lexical (task seeds, text fallback) is labeled as a hint.

Everything is deterministic (sorted, rounded tie-breaks). The token numbers are
honest *estimates* (chars ÷ 4), labeled as such.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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
from pyvisualizer.retrieval import (
    BM25Index,
    build_bm25,
    derive_seeds,
    function_source,
    rank_seeds,
    tokenize,
)

_CHARS_PER_TOKEN = 4  # rough, provider-agnostic estimate; explicitly labeled
_SEED_COUNT = 5  # a shortlist recovers from a wrong guess; a single seed cannot
_MAX_BODY_NODES = 10

_STRATEGIES = ("graph", "text", "hybrid")


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
    task: str = ""
    strategy: str = "graph"
    seeds: List[Dict[str, Any]] = field(default_factory=list)
    body_nodes: List[str] = field(default_factory=list)
    bodies: Dict[str, str] = field(default_factory=dict)
    fallback_used: bool = False

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


def _rank_candidates(
    G: nx.DiGraph,
    focus: List[str],
    exempt: List[str],
    pr: Dict[str, float],
) -> List[Tuple[str, bool]]:
    """Every admissible candidate as ``(node, is_exempt)`` in fill-priority order.

    Order: exempt focus, then budget-checked seeds (focus that is *not* exempt —
    e.g. task-derived seeds), then direct neighbours, then everything the focus
    can reach by personalized PageRank. Each group is rank-sorted with the
    deterministic ``(-score, name)`` tie-break.
    """
    focus_set = set(focus)
    exempt_set = set(exempt) & focus_set

    def rank(n: str) -> tuple:
        return (-round(pr.get(n, 0.0), 12), n)

    neighbours: set = set()
    for f in focus_set:
        if f in G:
            neighbours |= set(G.predecessors(f)) | set(G.successors(f))
    neighbours -= focus_set

    rest = [
        n
        for n in G.nodes()
        if n not in focus_set and n not in neighbours and pr.get(n, 0.0) > 0.0
    ]

    ordered: List[Tuple[str, bool]] = []
    ordered.extend((n, True) for n in sorted(exempt_set, key=rank))
    ordered.extend((n, False) for n in sorted(focus_set - exempt_set, key=rank))
    ordered.extend((n, False) for n in sorted(neighbours, key=rank))
    ordered.extend((n, False) for n in sorted(rest, key=rank))
    return ordered


def _select_nodes(
    G: nx.DiGraph,
    focus: List[str],
    budget_tokens: int,
    top: str,
    repo_url: str,
    exempt: Optional[List[str]] = None,
    pr: Optional[Dict[str, float]] = None,
) -> List[str]:
    """Focus first, then neighbours, then PageRank-ranked fill — all under budget.

    ``budget_tokens`` is a promise: an agent asking for a 4,000-token pack has
    4,000 tokens to spend. Only the ``exempt`` set (by default the whole focus)
    escapes the budget, because dropping what the caller explicitly asked about
    would be worse than overrunning. Task-derived seeds are focus but *not*
    exempt — they were inferred, not requested.

    The fill only considers functions the focus can actually reach through call
    edges. Padding the budget with unrelated functions is worse than leaving it
    unspent: it spends an agent's context on noise and dilutes the signal.

    Returns the selection in fill-priority order (callers sort for display).
    """
    focus_list = sorted(set(focus))
    if pr is None:
        pr = personalized_pagerank(G, focus_list) if focus_list else {}
    exempt_list = focus_list if exempt is None else sorted(set(exempt))

    selected: List[str] = []
    tokens = 0
    for n, is_exempt in _rank_candidates(G, focus_list, exempt_list, pr):
        c = _est_tokens(_node_line(G, n, top, repo_url))
        if not is_exempt and tokens + c > budget_tokens:
            # Skip this one and keep going: a single unusually long signature
            # must not halt the fill while cheaper, equally relevant functions
            # are still waiting. (Stopping here left 77% of packs under 75%
            # of their budget.)
            continue
        selected.append(n)
        tokens += c
    return selected


def _select_text(
    G: nx.DiGraph,
    ranked: List[Tuple[str, float]],
    budget_tokens: int,
    top: str,
    repo_url: str,
    exempt: List[str],
) -> List[str]:
    """Greedy fill straight down the lexical ranking — no graph expansion.

    Explicit focus stays exempt for the same reason as in ``_select_nodes``;
    everything else is budget-checked with the same skip-and-continue rule.
    Returns the selection in ranking order.
    """
    selected: List[str] = sorted(set(e for e in exempt if e in G))
    chosen = set(selected)
    tokens = sum(_est_tokens(_node_line(G, n, top, repo_url)) for n in selected)
    for node, _score in ranked:
        if node in chosen:
            continue
        c = _est_tokens(_node_line(G, node, top, repo_url))
        if tokens + c > budget_tokens:
            continue
        chosen.add(node)
        selected.append(node)
        tokens += c
    return selected


def _upgrade_bodies(
    G: nx.DiGraph,
    order: List[str],
    budget_tokens: int,
    spent_tokens: int,
) -> Dict[str, str]:
    """Upgrade the pack's focus functions from signature to full source.

    Bodies only spend the headroom the signature fill left, so breadth is never
    sacrificed for depth: a small task neighbourhood gets full code, a large one
    keeps its coverage. Only focus/seed functions are eligible — a full body for
    some unrelated function that happens to fit the leftover budget would be
    noise, and noise is what the budget exists to keep out. Unreadable source
    degrades to signature-only, silently — the pack must keep working on repos
    with a few broken files.
    """
    bodies: Dict[str, str] = {}
    cache: Dict[str, List[str]] = {}
    spent = spent_tokens
    for n in order:
        if len(bodies) >= _MAX_BODY_NODES:
            break
        data = G.nodes[n]
        src = function_source(
            data.get("path", ""),
            int(data.get("lineno", 0) or 0),
            int(data.get("end_lineno", 0) or 0),
            cache,
        )
        if not src:
            continue
        c = _est_tokens(src)
        if spent + c > budget_tokens:
            continue
        bodies[n] = src
        spent += c
    return bodies


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
    task: Optional[str] = None,
    strategy: Optional[str] = None,
    include_bodies: bool = True,
) -> ContextPack:
    """Build the deterministic, budget-bounded context pack model.

    ``task`` is a natural-language description of what the agent is about to do;
    it is turned into a shortlist of seeds (named symbols first, lexical matches
    second) that join the focus set. ``strategy`` picks how the pack is grown:

    - ``graph``  — verified call-graph expansion only (the default without a
      task; with a task, seeds come from symbol names in the text alone).
    - ``text``   — lexical (BM25) ranking only, no graph expansion.
    - ``hybrid`` — lexical seeds, graph expansion (the default with a task).
    """
    G = result.graph
    root = result.project_root
    top = _toplevel(root) or os.path.abspath(root)
    repo_url = repo_web_url(root)

    if strategy is None:
        strategy = "hybrid" if task else "graph"
    if strategy not in _STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; expected one of {_STRATEGIES}")
    if strategy in ("text", "hybrid") and not task:
        raise ValueError(f"strategy '{strategy}' needs a task description (--task)")

    focus_nodes = _resolve_focus(G, focus, from_git, root)
    # Only what the caller explicitly named escapes the budget. Task-derived
    # seeds are inferred, so they compete for budget like everything else.
    exempt = list(focus_nodes)

    seeds_info: List[Dict[str, Any]] = []
    bm25: Optional[BM25Index] = None
    if task:
        if strategy == "graph":
            # Pure-graph seeding: only symbols the task text actually names.
            for node in derive_seeds(task, G):
                seeds_info.append({"node": node, "score": 0.0, "source": "symbol"})
        else:
            bm25 = build_bm25(G)
            for node, score, source in rank_seeds(task, G, bm25, k=_SEED_COUNT):
                seeds_info.append({"node": node, "score": score, "source": source})

    fallback_used = False
    ranked_text: List[Tuple[str, float]] = []
    pr: Optional[Dict[str, float]] = None
    if strategy == "text":
        assert bm25 is not None
        ranked_text = bm25.rank(tokenize(task or ""))
        selection = _select_text(G, ranked_text, budget_tokens, top, repo_url, exempt)
        focus_out = sorted(set(exempt) | {s["node"] for s in seeds_info})
    else:
        teleport = sorted(set(focus_nodes) | {s["node"] for s in seeds_info})
        if not teleport:
            # No focus and no usable seeds → center on entry points (the app's
            # front doors). For a task this is a fallback and is labeled as one;
            # without a task it is the normal project-overview pack.
            from pyvisualizer.metrics import _is_entry_point

            teleport = sorted(
                n for n in G.nodes() if _is_entry_point(n, G.nodes[n]) and G.out_degree(n) > 0
            )
            # Still nothing (e.g. tiny lib) → every node is fair game.
            if not teleport:
                teleport = sorted(G.nodes())
            if task:
                fallback_used = True
            else:
                exempt = list(teleport)
        pr = personalized_pagerank(G, teleport) if teleport else {}
        selection = _select_nodes(G, teleport, budget_tokens, top, repo_url, exempt=exempt, pr=pr)
        focus_out = teleport
    # A non-empty graph must never produce an empty pack: under an impossible
    # budget with nothing exempt, keep the single best candidate anyway.
    if not selection and focus_out:
        selection = [focus_out[0]]

    # Bodies for the focus/seed functions take priority over breadth: an agent
    # is better served by the actual code of the five functions its task is
    # about than by the signature of the fortieth neighbour. Bodies are costed
    # against the focus signatures alone, then the breadth fill re-runs with
    # whatever budget the bodies left. (`include_bodies=False` restores the
    # signatures-only fill exactly.)
    bodies: Dict[str, str] = {}
    if include_bodies:
        focus_out_set = set(focus_out)
        focus_sigs = [n for n in selection if n in focus_out_set]
        spent = sum(_est_tokens(_node_line(G, n, top, repo_url)) for n in focus_sigs)
        bodies = _upgrade_bodies(G, focus_sigs, budget_tokens, spent)
        if bodies:
            body_cost = sum(_est_tokens(src) for src in bodies.values())
            refill_budget = budget_tokens - body_cost
            # Body-upgraded functions must survive the refill: their footprint
            # (signature + body) was already validated against the budget above.
            refill_exempt = sorted(set(exempt) | set(bodies))
            if strategy == "text":
                selection = _select_text(
                    G, ranked_text, refill_budget, top, repo_url, refill_exempt
                )
            else:
                selection = _select_nodes(
                    G, focus_out, refill_budget, top, repo_url, exempt=refill_exempt, pr=pr
                )

    included = sorted(selection)
    included_set = set(included)
    focus_nodes = focus_out

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

    cycles: List[List[str]] = []
    for c in find_cycles(G):
        if included_set & set(c):
            # Rotate to the lexicographically smallest node so the rendered
            # chain is identical run-to-run (simple_cycles' start node isn't).
            i = c.index(min(c))
            cycles.append(list(c[i:]) + list(c[:i]))
    cycles.sort()
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
        task=task or "",
        strategy=strategy,
        seeds=seeds_info,
        body_nodes=sorted(bodies),
        bodies=bodies,
        fallback_used=fallback_used,
    )
    # Estimate the pack size from its payload (nodes + edges + cycles + bodies),
    # i.e. what an agent actually spends tokens on — computed before rendering
    # the header, which then simply displays the number.
    body = "\n".join(rendered_nodes)
    body += "\n".join(
        f"{e['caller']} {e['callee']} {e['confidence']} {e['provenance']}" for e in edges
    )
    body += "\n".join(" ".join(c) for c in cycles)
    body += "\n".join(bodies[n] for n in sorted(bodies))
    pack.est_pack_tokens = _est_tokens(body)
    return pack


def render_pack_markdown(pack: ContextPack) -> str:
    lines: List[str] = [f"# Context Pack — {pack.project_name}"]
    lines.append("")
    body_hint = (
        "Full source is included below for the top-ranked functions; open the "
        "cited `file:line` for the rest."
        if pack.bodies
        else "Open the cited `file:line` when you need a function body."
    )
    lines.append(
        "> Verified, task-scoped architecture facts from py-code-visualizer. "
        "Every function below is real and every call edge is parsed from the "
        "AST with `file:line` provenance — use these as ground truth instead of "
        f"re-deriving structure from source. {body_hint}"
    )
    lines.append("")
    if pack.task:
        lines.append(f"- Task: {pack.task}")
        lines.append(f"- Strategy: {pack.strategy}")
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

    if pack.seeds:
        lines.append("## Seeds (task → code, best first)")
        lines.append("")
        lines.append(
            "_Seeds are how the task description was mapped onto this codebase: "
            "`symbol` means the task named it; `bm25` is a lexical match — a "
            "hint, not a verified fact._"
        )
        lines.append("")
        for seed in pack.seeds:
            lines.append(f"- `{seed['node']}` — {seed['score']} · {seed['source']}")
        lines.append("")

    if pack.fallback_used:
        lines.append(
            "> **Fallback:** no reliable seeds could be derived from the task "
            "description, so this pack falls back to "
            + (
                "top lexical matches — treat them as hints, not verified localization."
                if pack.strategy != "graph"
                else "the project's entry points — treat this as an overview, not localization."
            )
        )
        lines.append("")

    if pack.bodies:
        lines.append("## Function bodies (top-ranked)")
        lines.append("")
        for n in pack.body_nodes:
            lines.append(f"### `{n}`")
            lines.append("")
            lines.append("```python")
            lines.append(pack.bodies[n].rstrip("\n"))
            lines.append("```")
            lines.append("")

    lines.append("## Functions")
    lines.append("")
    body_set = set(pack.body_nodes)
    for node, rendered in zip(pack.included, pack.rendered_nodes):
        if node in body_set:
            rendered += " _(full source above)_"
        lines.append(rendered)
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
    # @2 is strictly additive over @1: every @1 key is unchanged; new keys are
    # task/strategy/seeds/tiers/fallback_used. Consumers keying on @1 fields
    # keep working.
    data = {
        "schema": "pyvisualizer/context@2",
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
        "task": pack.task,
        "strategy": pack.strategy,
        "seeds": pack.seeds,
        "tiers": {n: ("body" if n in set(pack.body_nodes) else "signature") for n in pack.included},
        "fallback_used": pack.fallback_used,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)
