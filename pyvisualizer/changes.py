"""
Change detection — the shared engine behind ``review`` and ``context``.

Both the human-facing review report and the machine-facing context pack start
from the same question: *given a diff, which functions changed?* This module
answers it deterministically from git, maps changed lines onto graph nodes
(which already carry ``path`` / ``lineno`` / ``end_lineno``), and derives the
repository web URL used to make every reference clickable.

All git access degrades gracefully: outside a repository, or with no base to
diff against, the functions return empty results and callers simply fall back
to analyzing the whole project. Web links use ``blob/HEAD`` (never a commit
SHA) so regenerated artifacts stay byte-identical on unchanged code.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import networkx as nx

from pyvisualizer.overlays import _git, _toplevel

logger = logging.getLogger("pyvisualizer.changes")

LineRange = Tuple[int, int]

# @@ -old[,n] +new[,n] @@  — we only need the new-side start/count.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# Candidate base refs, tried in order when the caller doesn't name one.
_DEFAULT_BASES = ("origin/main", "origin/master", "main", "master", "HEAD~1")


def _ref_exists(project_root: str, ref: str) -> bool:
    try:
        proc = _git(project_root, "rev-parse", "--verify", "--quiet", ref)
    except (FileNotFoundError, OSError):
        return False
    return proc.returncode == 0


def resolve_base_ref(project_root: str, base_ref: Optional[str]) -> str:
    """Return a usable base ref to diff against, or "" if none is available.

    An explicit ``base_ref`` wins if it resolves; otherwise the common defaults
    (origin/main, main, …) are tried in order.
    """
    if base_ref:
        if _ref_exists(project_root, base_ref):
            return base_ref
        logger.debug("Requested base ref %r not found; auto-detecting.", base_ref)
    for cand in _DEFAULT_BASES:
        if _ref_exists(project_root, cand):
            return cand
    return ""


def changed_lines_from_git(
    project_root: str, base_ref: Optional[str] = None
) -> Dict[str, List[LineRange]]:
    """Map ``git_relative_path -> [(start, end), ...]`` of changed line ranges.

    Compares the base ref against the **working tree** (``git diff <base>``), so
    both committed and uncommitted changes count — the same set a reviewer or an
    agent is actually about to reason about. Ranges are on the new (current)
    side of the diff, which is what maps onto the freshly built graph.
    """
    base = resolve_base_ref(project_root, base_ref)
    if not base:
        logger.debug("No base ref available; treating as no changes.")
        return {}
    try:
        proc = _git(project_root, "diff", "--unified=0", "--no-color", base)
    except (FileNotFoundError, OSError):
        return {}
    if proc.returncode != 0:
        logger.debug("git diff against %s failed; skipping change detection.", base)
        return {}

    changed: Dict[str, List[LineRange]] = {}
    current_file: Optional[str] = None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ "):
            # "+++ b/path/to/file.py" or "+++ /dev/null" for deletions.
            target = line[4:].strip()
            if target == "/dev/null":
                current_file = None
            else:
                path = target[2:] if target.startswith("b/") else target
                current_file = path if path.endswith(".py") else None
            continue
        if current_file is None:
            continue
        m = _HUNK_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        if count <= 0:
            continue  # pure deletion — no line exists in the current tree
        changed.setdefault(current_file, []).append((start, start + count - 1))
    for ranges in changed.values():
        ranges.sort()
    return changed


def _rel_to_toplevel(path: str, top: str) -> str:
    # realpath both sides: git reports its top-level with symlinks resolved
    # (e.g. macOS /var -> /private/var), while node paths may not be, and a
    # mismatch would silently break line→function mapping and link rels.
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(top)).replace(os.sep, "/")
    except ValueError:
        return path.replace(os.sep, "/")


def map_lines_to_functions(
    G: nx.DiGraph,
    changed: Dict[str, List[LineRange]],
    project_root: str,
) -> List[str]:
    """Return the sorted node ids whose line span intersects a changed range."""
    if not changed:
        return []
    top = _toplevel(project_root) or os.path.abspath(project_root)
    hits: List[str] = []
    for node in G.nodes():
        data = G.nodes[node]
        path = data.get("path", "")
        if not path:
            continue
        rel = _rel_to_toplevel(path, top)
        ranges = changed.get(rel)
        if not ranges:
            continue
        start = int(data.get("lineno", 0) or 0)
        end = int(data.get("end_lineno", start) or start)
        if end < start:
            end = start
        if any(not (end < rs or start > re_) for rs, re_ in ranges):
            hits.append(node)
    return sorted(hits)


def repo_web_url(project_root: str) -> str:
    """Return the normalized https web URL of ``origin``, or "" if none.

    Handles the common GitHub/GitLab SSH and HTTPS remote forms. The result is
    a base URL with no trailing slash or ``.git`` — append ``/blob/HEAD/<file>``.
    """
    try:
        proc = _git(project_root, "remote", "get-url", "origin")
    except (FileNotFoundError, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    url: str = proc.stdout.strip()
    if not url:
        return ""
    # scp-like: git@github.com:owner/repo.git -> https://github.com/owner/repo
    m = re.match(r"^[\w.-]+@([\w.-]+):(.+)$", url)
    if m:
        url = f"https://{m.group(1)}/{m.group(2)}"
    elif url.startswith("ssh://"):
        url = "https://" + url[len("ssh://") :]
        url = re.sub(r"https://[^/@]+@", "https://", url)  # strip any user@
    if url.endswith(".git"):
        url = url[:-4]
    return url.rstrip("/")


def web_link(repo_url: str, file_rel: str, lineno: int) -> str:
    """Build a ``blob/HEAD`` web link (deterministic — never a commit SHA)."""
    if not repo_url or not file_rel:
        return ""
    anchor = f"#L{lineno}" if lineno else ""
    return f"{repo_url}/blob/HEAD/{file_rel}{anchor}"


class Linker:
    """Render a graph node as a link (markdown) or plain reference (text).

    Shared by ``review`` and ``impact`` so every human-facing report links the
    same way: an absolute GitHub link when a remote is detectable (PR comments
    can't use relative links), otherwise a plain ``file:line`` that any IDE
    resolves.
    """

    def __init__(self, G: nx.DiGraph, project_root: str, markdown: bool):
        self.G = G
        self.markdown = markdown
        self.repo_url = repo_web_url(project_root) if markdown else ""
        self.top = _toplevel(project_root) or os.path.abspath(project_root)

    def _rel(self, path: str) -> str:
        return _rel_to_toplevel(path, self.top)

    def ref(self, node: str) -> str:
        data = self.G.nodes[node] if node in self.G else {}
        path = data.get("path", "")
        lineno = int(data.get("lineno", 0) or 0)
        if not path:
            return f"`{node}`"
        rel = self._rel(path)
        loc = f"{rel}:{lineno}" if lineno else rel
        if self.markdown and self.repo_url:
            return f"[`{node}`]({web_link(self.repo_url, rel, lineno)})"
        return f"`{node}` ({loc})"
