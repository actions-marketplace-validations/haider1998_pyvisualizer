"""Leak-free seeding: issue text → candidate focus symbols.

This is the crux of experimental validity. `context --focus` needs a starting
symbol, but for an *unsolved* issue nobody knows one yet — so the seed must be
derivable from what a developer actually has at that moment: the bug report.

**Invariant: this module never sees the gold patch.** ``derive_seeds`` takes the
problem statement and the graph, and nothing else. If it took the patch, every
downstream number would be meaningless, so the signature is the enforcement and
``tests`` asserts it.

Extraction is deliberately dumb and transparent — backticked code spans, dotted
paths, and identifier-shaped words — because a clever extractor would itself
become an untested confound.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence, Set

import networkx as nx

# Identifier-ish tokens: snake_case, CamelCase, and dotted paths.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_MIN_LEN = 4

# Words that look like identifiers but carry no localization signal. Kept short
# and generic on purpose — a big hand-tuned list would be tuning on the test set.
_STOPWORDS = {
    "self",
    "none",
    "true",
    "false",
    "return",
    "class",
    "def",
    "import",
    "from",
    "print",
    "python",
    "error",
    "traceback",
    "exception",
    "value",
    "type",
    "test",
    "tests",
    "code",
    "line",
    "file",
    "this",
    "that",
    "with",
    "when",
    "then",
    "should",
    "would",
    "expected",
    "actual",
    "result",
    "output",
    "input",
    "version",
    "issue",
    "bug",
    "example",
    "following",
    "above",
    "below",
    "using",
    "used",
    "does",
    "make",
    "like",
    "also",
    "there",
    "here",
    "will",
    "have",
    "which",
    "what",
    "where",
    "some",
    "only",
    "same",
    "instead",
    "however",
    "because",
}


def extract_identifiers(problem_statement: str) -> List[str]:
    """Pull identifier-shaped tokens out of an issue report, best signal first.

    Tokens inside backticks are ranked ahead of prose tokens: when a reporter
    writes `` `Model.save` `` they are naming the thing, not describing it.
    """
    ranked: List[str] = []
    seen: Set[str] = set()

    def _add(tok: str) -> None:
        tok = tok.strip().strip(".")
        if len(tok) < _MIN_LEN or tok.lower() in _STOPWORDS:
            return
        if tok not in seen:
            seen.add(tok)
            ranked.append(tok)

    for span in _BACKTICK_RE.findall(problem_statement):
        for tok in _IDENT_RE.findall(span):
            _add(tok)
    for tok in _IDENT_RE.findall(problem_statement):
        _add(tok)
    return ranked


def _index(G: nx.DiGraph) -> Dict[str, List[str]]:
    """short name (and dotted suffixes) → node ids."""
    idx: Dict[str, List[str]] = {}
    for node in G.nodes():
        parts = node.split(".")
        # Index the last 1..3 segments so `save`, `Model.save`, `db.Model.save` hit.
        for depth in range(1, min(3, len(parts)) + 1):
            key = ".".join(parts[-depth:])
            idx.setdefault(key, []).append(node)
    return {k: sorted(v) for k, v in idx.items()}


def derive_seeds(
    problem_statement: str,
    G: nx.DiGraph,
    *,
    max_seeds: int = 10,
    max_nodes_per_token: int = 5,
) -> List[str]:
    """Return focus node ids implied by the issue text alone.

    ``max_nodes_per_token`` drops hopelessly generic names: a token matching 400
    nodes (``save``, ``get``) localizes nothing and would just flood the budget.
    """
    idx = _index(G)
    seeds: List[str] = []
    seen: Set[str] = set()
    for token in extract_identifiers(problem_statement):
        for key in (token, token.split(".")[-1]):
            matches = idx.get(key)
            if not matches or len(matches) > max_nodes_per_token:
                continue
            for node in matches:
                if node not in seen:
                    seen.add(node)
                    seeds.append(node)
            break
        if len(seeds) >= max_seeds:
            break
    return seeds[:max_seeds]


def seed_files(seeds: Sequence[str], G: nx.DiGraph) -> List[str]:
    """The distinct files the seed nodes live in."""
    out: Set[str] = set()
    for node in seeds:
        path = G.nodes[node].get("path", "")
        if path:
            out.add(path)
    return sorted(out)
