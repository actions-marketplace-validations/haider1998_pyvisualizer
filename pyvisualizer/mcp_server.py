"""
MCP server — the verified call graph as pull-model tools for coding agents.

A pre-built context pack is a guess about what an agent will need; a tool the
agent calls mid-task answers the question it actually has. This server exposes
the same engine as the CLI through three deliberately few, high-signal tools:

- ``search_code``  — lexical (BM25) search over every function's name and source.
- ``context_pack`` — the budget-bounded verified context pack (``context`` command).
- ``impact``       — blast radius: who calls this, what does it call, what breaks.

The server is long-lived, so the graph and the search index are built lazily
and cached in memory, invalidated by a fingerprint of the project's Python
files (path, mtime, size). Nothing is written to disk and no code is executed —
same guarantees as the CLI.

The ``mcp`` SDK (Python ≥3.10) is an optional extra: ``pip install
'py-code-visualizer[mcp]'``. The tool layer below is plain functions so it
works — and is tested — without the SDK installed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from typing import Optional, Tuple

from pyvisualizer.api import GraphResult, build_graph
from pyvisualizer.retrieval import BM25Index, build_bm25
from pyvisualizer.utils.file_discovery import find_project_python_files, parse_python_file


class ProjectSession:
    """Lazily-built, fingerprint-invalidated graph + search index for one project."""

    def __init__(self, project_root: str) -> None:
        self.project_root = os.path.abspath(project_root)
        self._fingerprint: Optional[str] = None
        self._graph: Optional[GraphResult] = None
        self._bm25: Optional[BM25Index] = None

    def _current_fingerprint(self) -> str:
        h = hashlib.sha256()
        for path in find_project_python_files(self.project_root):
            try:
                st = os.stat(path)
            except OSError:
                continue
            h.update(f"{path}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
        return h.hexdigest()

    def get(self) -> Tuple[GraphResult, BM25Index]:
        fp = self._current_fingerprint()
        if self._graph is None or self._bm25 is None or fp != self._fingerprint:
            # parse_python_file caches ASTs by path; a long-lived server must
            # drop that cache or a rebuild would re-serve stale parses.
            parse_python_file.cache_clear()
            self._graph = build_graph(self.project_root)
            self._bm25 = build_bm25(self._graph.graph)
            self._fingerprint = fp
        return self._graph, self._bm25


def tool_search_code(session: ProjectSession, query: str, k: int = 10) -> str:
    """Lexical search over every function's qualified name, file, and source."""
    result, bm25 = session.get()
    hits = bm25.search(query, k=max(1, min(int(k), 50)))
    if not hits:
        return f"No functions matched {query!r}. Try different words or an identifier."
    G = result.graph
    lines = []
    for node, score in hits:
        data = G.nodes[node]
        path = data.get("path", "")
        rel = os.path.relpath(path, session.project_root) if path else "?"
        lines.append(f"- `{node}` — {rel}:{data.get('lineno', 0)} (score {round(score, 2)})")
    return "\n".join(lines)


def tool_context_pack(
    session: ProjectSession,
    task: str = "",
    focus: str = "",
    budget_tokens: int = 4000,
    strategy: str = "",
) -> str:
    """Budget-bounded, verified context pack for a task and/or focus symbols."""
    from pyvisualizer.context import build_context_pack, render_pack_markdown

    result, _ = session.get()
    focus_list = [f.strip() for f in focus.split(",") if f.strip()] or None
    try:
        pack = build_context_pack(
            result,
            focus=focus_list,
            budget_tokens=max(200, int(budget_tokens)),
            task=task or None,
            strategy=strategy or None,
        )
    except ValueError as e:
        return f"Cannot build pack: {e}"
    return render_pack_markdown(pack)


def tool_impact(session: ProjectSession, symbol: str) -> str:
    """Blast radius of one function: direct/transitive callers and callees."""
    from pyvisualizer.impact import analyze_impact, render_markdown, resolve_target

    result, bm25 = session.get()
    G = result.graph
    if resolve_target(G, symbol) is None:
        closest = ", ".join(f"`{n}`" for n, _ in bm25.search(symbol, k=3))
        hint = f" Closest matches: {closest}." if closest else ""
        return f"Symbol not found (or ambiguous): `{symbol}`.{hint}"
    return render_markdown(analyze_impact(G, symbol), G, result.project_root)


def _register(mcp_app, session: ProjectSession) -> None:  # type: ignore[no-untyped-def]
    """Attach the three tools to a FastMCP app. Split out for testability."""

    @mcp_app.tool()
    def search_code(query: str, k: int = 10) -> str:
        """Search this Python project's functions lexically (names + source).

        Use this first to find where something lives. Returns up to k functions
        as `qualified.name — file:line (score)`.
        """
        return tool_search_code(session, query, k)

    @mcp_app.tool()
    def context_pack(
        task: str = "", focus: str = "", budget_tokens: int = 4000, strategy: str = ""
    ) -> str:
        """Verified, budget-bounded context pack for a coding task.

        Pass `task` (natural-language description of what you're about to do)
        and/or `focus` (comma-separated function/class/file names). Returns
        AST-verified call edges with file:line provenance, plus full source for
        the top-ranked functions. strategy: graph|text|hybrid (default hybrid
        for tasks).
        """
        return tool_context_pack(session, task, focus, budget_tokens, strategy)

    @mcp_app.tool()
    def impact(symbol: str) -> str:
        """Blast radius of one function/method: who calls it (direct and
        transitive), what it calls, and which modules are affected. Use before
        changing a function to see what could break.
        """
        return tool_impact(session, symbol)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pyvisualizer-mcp",
        description="MCP server exposing a Python project's verified call graph to agents",
    )
    parser.add_argument("path", nargs="?", default=".", help="Project root (default: cwd)")
    args = parser.parse_args(argv)

    if sys.version_info < (3, 10):
        print(
            "pyvisualizer-mcp needs Python 3.10+ (the MCP SDK's minimum). "
            "The rest of py-code-visualizer still works on this interpreter.",
            file=sys.stderr,
        )
        return 1
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "MCP support is an optional extra. Install it with:\n"
            "    pip install 'py-code-visualizer[mcp]'",
            file=sys.stderr,
        )
        return 1

    session = ProjectSession(args.path)
    app = FastMCP("pyvisualizer")
    _register(app, session)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
