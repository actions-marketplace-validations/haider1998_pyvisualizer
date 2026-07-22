"""The competing context strategies ("arms"), all held to the same token budget.

Every arm answers the same question — *given this issue and this repository, which
functions should an agent be shown?* — and every arm pays for its answer with the
same token estimator, so the comparison is about **what** you select, never about
who was allowed to select more.

Arms:

``bm25``            Classic lexical retrieval over function source. This is the
                    honest, strong baseline: SWE-bench ships BM25 retrieval, and
                    unlike the graph arms it gets to read the actual code.
``context_shipped`` Reproduces py-code-visualizer v2.2 exactly — including the
                    all-zero-score bug that degraded selection to alphabetical
                    order. Present to quantify the damage, not to flatter.
``context_fixed``   The repaired selection (personalized PageRank over call edges).
``hybrid``          BM25 picks the entry points, the call graph expands them.
                    Tests the real product hypothesis: text finds *where to look*,
                    the verified graph finds *what it touches*.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Dict, List, Optional, Sequence, Set

import networkx as nx

from pyvisualizer.api import GraphResult
from pyvisualizer.context import _est_tokens, _node_line, build_context_pack
from pyvisualizer.overlays import _toplevel

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

ARMS = ("bm25", "context_shipped", "context_fixed", "hybrid")


# --------------------------------------------------------------------------- #
# Shared costing — identical for every arm
# --------------------------------------------------------------------------- #
def node_cost(G: nx.DiGraph, node: str, top: str) -> int:
    """What one function costs in the rendered pack (chars÷4, as the tool reports)."""
    return _est_tokens(_node_line(G, node, top, ""))


def _split_identifier(tok: str) -> List[str]:
    """`get_user_name` / `GetUserName` → the words inside, for lexical matching."""
    parts = re.split(r"_+", tok)
    out: List[str] = []
    for p in parts:
        out.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", p) or [p])
    return [w.lower() for w in out if w]


def tokenize(text: str) -> List[str]:
    out: List[str] = []
    for tok in _TOKEN_RE.findall(text):
        low = tok.lower()
        out.append(low)
        words = _split_identifier(tok)
        if len(words) > 1:
            out.extend(words)
    return out


# --------------------------------------------------------------------------- #
# BM25 over function bodies
# --------------------------------------------------------------------------- #
class BM25:
    """Okapi BM25. Standard parameters (k1=1.5, b=0.75); no tuning on results."""

    def __init__(self, docs: Dict[str, List[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.ids = sorted(docs)
        self.tf = {d: Counter(docs[d]) for d in self.ids}
        self.len = {d: len(docs[d]) for d in self.ids}
        self.avg = (sum(self.len.values()) / len(self.ids)) if self.ids else 0.0
        df: Counter = Counter()
        for d in self.ids:
            df.update(set(self.tf[d]))
        n = len(self.ids)
        self.idf = {t: math.log(1.0 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def rank(self, query: Sequence[str]) -> List[str]:
        scores: Dict[str, float] = {}
        for doc in self.ids:
            tf, dl = self.tf[doc], self.len[doc]
            s = 0.0
            for term in query:
                f = tf.get(term)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avg or 1.0))
                s += self.idf.get(term, 0.0) * f * (self.k1 + 1) / denom
            if s > 0:
                scores[doc] = s
        # Deterministic: score desc, then node id.
        return sorted(scores, key=lambda d: (-round(scores[d], 12), d))


def _function_source(path: str, start: int, end: int, cache: Dict[str, List[str]]) -> str:
    lines = cache.get(path)
    if lines is None:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            lines = []
        cache[path] = lines
    if not lines:
        return ""
    return "".join(lines[max(0, start - 1) : min(len(lines), end)])


def build_bm25(G: nx.DiGraph) -> BM25:
    """One document per function: its qualified name, file path, and source."""
    cache: Dict[str, List[str]] = {}
    docs: Dict[str, List[str]] = {}
    for node in G.nodes():
        data = G.nodes[node]
        path = data.get("path", "")
        start = int(data.get("lineno", 0) or 0)
        end = int(data.get("end_lineno", start) or start)
        body = _function_source(path, start, end, cache) if path else ""
        docs[node] = tokenize(node) + tokenize(os.path.basename(path)) + tokenize(body)
    return BM25(docs)


# --------------------------------------------------------------------------- #
# Selection strategies
# --------------------------------------------------------------------------- #
def select_bm25(G: nx.DiGraph, ranked: Sequence[str], budget_tokens: int, top: str) -> List[str]:
    chosen: List[str] = []
    spent = 0
    for node in ranked:
        cost = node_cost(G, node, top)
        if spent + cost > budget_tokens:
            break
        chosen.append(node)
        spent += cost
    return sorted(chosen)


def select_context_shipped(
    G: nx.DiGraph, focus: Sequence[str], budget_tokens: int, top: str
) -> List[str]:
    """Reproduces the shipped v2.2 path: focus + neighbours, then *alphabetical* fill.

    Not a strawman — this is what `context` actually emitted on any machine
    without SciPy installed, which is the default install.
    """
    base: Set[str] = set(focus)
    for f in focus:
        if f in G:
            base |= set(G.predecessors(f)) | set(G.successors(f))
    chosen = sorted(base)
    spent = sum(node_cost(G, n, top) for n in chosen)
    for node in sorted(n for n in G.nodes() if n not in base):
        cost = node_cost(G, node, top)
        if spent + cost > budget_tokens:
            break
        chosen.append(node)
        spent += cost
    return sorted(chosen)


def run_arm(
    arm: str,
    result: GraphResult,
    seeds: Sequence[str],
    problem_statement: str,
    budget_tokens: int,
    bm25: Optional[BM25] = None,
    hybrid_seed_count: int = 5,
) -> List[str]:
    """Return the functions this arm would put in front of the agent."""
    G = result.graph
    top = _toplevel(result.project_root) or os.path.abspath(result.project_root)
    query = tokenize(problem_statement)

    if arm == "bm25":
        assert bm25 is not None
        return select_bm25(G, bm25.rank(query), budget_tokens, top)

    if arm == "context_shipped":
        return select_context_shipped(G, seeds, budget_tokens, top)

    if arm == "context_fixed":
        if not seeds:
            return []
        return list(
            build_context_pack(result, focus=list(seeds), budget_tokens=budget_tokens).included
        )

    if arm == "hybrid":
        assert bm25 is not None
        lexical_seeds = bm25.rank(query)[:hybrid_seed_count]
        if not lexical_seeds:
            return []
        return list(
            build_context_pack(
                result, focus=list(lexical_seeds), budget_tokens=budget_tokens
            ).included
        )

    raise ValueError(f"unknown arm: {arm}")


# --------------------------------------------------------------------------- #
# Scoring — the standard localization metrics from the literature
# --------------------------------------------------------------------------- #
def _rel(path: str, top: str) -> str:
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(top)).replace(os.sep, "/")
    except ValueError:
        return path


def score(
    G: nx.DiGraph,
    selected: Sequence[str],
    gold_files: Set[str],
    gold_functions: Set[str],
    top: str,
    repo_root: str,
) -> Dict[str, float]:
    """File-level P/R/F1 + Jaccard and function-level recall, plus token cost."""
    pred_files: Set[str] = set()
    for node in selected:
        path = G.nodes[node].get("path", "")
        if path:
            pred_files.add(_rel(path, repo_root))
    pred_funcs = set(selected)

    tp = len(pred_files & gold_files)
    precision = tp / len(pred_files) if pred_files else 0.0
    recall = tp / len(gold_files) if gold_files else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    union = len(pred_files | gold_files)
    jaccard = tp / union if union else 0.0

    fn_hits = len(pred_funcs & gold_functions)
    fn_recall = fn_hits / len(gold_functions) if gold_functions else 0.0

    tokens = sum(_est_tokens(_node_line(G, n, top, "")) for n in selected)
    return {
        "selected": len(selected),
        "tokens": tokens,
        "file_precision": round(precision, 4),
        "file_recall": round(recall, 4),
        "file_f1": round(f1, 4),
        "file_jaccard": round(jaccard, 4),
        "func_recall": round(fn_recall, 4),
        "func_hits": fn_hits,
        "any_gold_file_found": 1.0 if tp else 0.0,
        "any_gold_func_found": 1.0 if fn_hits else 0.0,
        # The efficiency metric the product claim is really about.
        "func_recall_per_1k": round(fn_recall / (tokens / 1000.0), 4) if tokens else 0.0,
        "file_recall_per_1k": round(recall / (tokens / 1000.0), 4) if tokens else 0.0,
    }
