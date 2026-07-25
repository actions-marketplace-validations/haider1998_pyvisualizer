"""
Lexical retrieval — prose → ranked code locations, with zero new dependencies.

The call graph answers "what does this touch?", but it cannot answer "where do I
start?" from a natural-language task description: a symbol-exact resolver needs
a symbol, and an unsolved task rarely names one reliably. This module supplies
that missing first step with two deliberately transparent mechanisms:

- **Identifier extraction** (``extract_identifiers`` / ``derive_seeds``): pull
  identifier-shaped tokens out of the prose — backticked spans first, because
  when someone writes `` `Model.save` `` they are naming the thing, not
  describing it — and map them onto graph nodes. Dumb on purpose: a clever
  extractor would be an untested confound.
- **Okapi BM25** (``BM25Index`` / ``build_bm25``): classic lexical ranking over
  one document per function — its qualified name, file basename, and actual
  source slice. Standard parameters (k1=1.5, b=0.75), no tuning.

Both are pure stdlib, and both are deterministic: every ranking breaks ties on
``(-round(score, 12), node_id)`` so output is byte-identical across machines.
Nothing here is "verified" in the call-graph sense — lexical hits are *hints*,
and callers must label them as such (the context pack does).
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Dict, List, Optional, Sequence, Set, Tuple

import networkx as nx

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Identifier-ish tokens in prose: snake_case, CamelCase, and dotted paths.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_MIN_LEN = 4

# Words that look like identifiers but carry no localization signal. Kept short
# and generic on purpose — a big hand-tuned list would be tuning on anecdotes.
_STOPWORDS = {
    "self", "none", "true", "false", "return", "class", "def", "import", "from",
    "print", "python", "error", "traceback", "exception", "value", "type",
    "test", "tests", "code", "line", "file", "this", "that", "with", "when",
    "then", "should", "would", "expected", "actual", "result", "output",
    "input", "version", "issue", "bug", "example", "following", "above",
    "below", "using", "used", "does", "make", "like", "also", "there", "here",
    "will", "have", "which", "what", "where", "some", "only", "same",
    "instead", "however", "because",
}


def _split_identifier(tok: str) -> List[str]:
    """``get_user_name`` / ``GetUserName`` → the words inside, for lexical matching."""
    parts = re.split(r"_+", tok)
    out: List[str] = []
    for p in parts:
        out.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", p) or [p])
    return [w.lower() for w in out if w]


def tokenize(text: str) -> List[str]:
    """Lowercased tokens plus the words hidden inside compound identifiers."""
    out: List[str] = []
    for tok in _TOKEN_RE.findall(text):
        out.append(tok.lower())
        words = _split_identifier(tok)
        if len(words) > 1:
            out.extend(words)
    return out


def function_source(
    path: str,
    start: int,
    end: int,
    cache: Optional[Dict[str, List[str]]] = None,
) -> str:
    """The source slice ``path[start:end]`` (1-based, inclusive). Never raises.

    Unreadable files (missing, permission, non-UTF8 garbage) degrade to ``""``;
    a missing/bogus end line degrades to the ``def`` line alone. Retrieval and
    rendering must keep working on repos with a few broken files.
    """
    if not path:
        return ""
    lines = cache.get(path) if cache is not None else None
    if lines is None:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            lines = []
        if cache is not None:
            cache[path] = lines
    if not lines or start <= 0:
        return ""
    if end < start:
        end = start
    return "".join(lines[start - 1 : min(len(lines), end)])


class BM25Index:
    """Okapi BM25 over a fixed document set. Standard parameters, no tuning."""

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

    def rank(self, query: Sequence[str]) -> List[Tuple[str, float]]:
        """Positively-scored docs for pre-tokenized ``query``, best first."""
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
        ordered = sorted(scores, key=lambda d: (-round(scores[d], 12), d))
        return [(d, scores[d]) for d in ordered]

    def search(self, query: str, k: int = 10) -> List[Tuple[str, float]]:
        """Top-``k`` documents for a natural-language query."""
        return self.rank(tokenize(query))[:k]


def build_bm25(G: nx.DiGraph) -> BM25Index:
    """One document per function: its qualified name, file basename, and source."""
    cache: Dict[str, List[str]] = {}
    docs: Dict[str, List[str]] = {}
    for node in G.nodes():
        data = G.nodes[node]
        path = data.get("path", "")
        start = int(data.get("lineno", 0) or 0)
        end = int(data.get("end_lineno", start) or start)
        body = function_source(path, start, end, cache)
        docs[node] = tokenize(node) + tokenize(os.path.basename(path)) + tokenize(body)
    return BM25Index(docs)


def extract_identifiers(text: str) -> List[str]:
    """Identifier-shaped tokens in the prose, best signal first (backticks win)."""
    ranked: List[str] = []
    seen: Set[str] = set()

    def _add(tok: str) -> None:
        tok = tok.strip().strip(".")
        if len(tok) < _MIN_LEN or tok.lower() in _STOPWORDS:
            return
        if tok not in seen:
            seen.add(tok)
            ranked.append(tok)

    for span in _BACKTICK_RE.findall(text):
        for tok in _IDENT_RE.findall(span):
            _add(tok)
    for tok in _IDENT_RE.findall(text):
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
    text: str,
    G: nx.DiGraph,
    *,
    max_seeds: int = 10,
    max_nodes_per_token: int = 5,
) -> List[str]:
    """Focus node ids implied by the task text alone.

    ``max_nodes_per_token`` drops hopelessly generic names: a token matching 400
    nodes (``save``, ``get``) localizes nothing and would just flood the budget.
    """
    idx = _index(G)
    seeds: List[str] = []
    seen: Set[str] = set()
    for token in extract_identifiers(text):
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


def rank_seeds(
    task: str,
    G: nx.DiGraph,
    bm25: BM25Index,
    k: int = 5,
) -> List[Tuple[str, float, str]]:
    """Ranked ``(node, score, source)`` seeds for a prose task.

    Symbol-derived seeds come first — a name the task actually uses beats any
    statistical match — then BM25 hits fill the remaining slots. Multiple seeds
    on purpose: expansion from a shortlist recovers from any single wrong guess,
    where a single best-guess seed cannot.
    """
    ranked = bm25.rank(tokenize(task))
    hits = dict(ranked)
    out: List[Tuple[str, float, str]] = []
    taken: Set[str] = set()
    for node in derive_seeds(task, G):
        if len(out) >= k:
            break
        if node not in taken:
            taken.add(node)
            out.append((node, round(hits.get(node, 0.0), 4), "symbol"))
    for node, score in ranked:
        if len(out) >= k:
            break
        if node not in taken:
            taken.add(node)
            out.append((node, round(score, 4), "bm25"))
    return out
