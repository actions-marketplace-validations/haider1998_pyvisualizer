"""
Data overlays: git churn (change frequency).

Overlays annotate nodes with an external signal the viewer can paint as a
heatmap. Churn answers "which code changes the most" — and combined with the
graph's centrality, surfaces the high-churn, high-blast-radius functions where
the next incident is most likely to live. Degrades gracefully outside a git
repo (returns empty, viewer simply omits the overlay).
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Dict

import networkx as nx

logger = logging.getLogger("pyvisualizer.overlays")


def _git(project_root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", project_root, *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _toplevel(project_root: str) -> str:
    try:
        proc = _git(project_root, "rev-parse", "--show-toplevel")
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_churn(project_root: str) -> Dict[str, int]:
    """Return ``{repo_relative_path: commit_count}`` from git history.

    Keys are relative to the git repository root (git's native output). Returns
    an empty dict if git is unavailable or this is not a repository.
    """
    try:
        proc = _git(project_root, "log", "--pretty=format:%H", "--name-only")
    except (FileNotFoundError, subprocess.SubprocessError):
        logger.debug("git not available; skipping churn overlay.")
        return {}
    if proc.returncode != 0:
        logger.debug("Not a git repository; skipping churn overlay.")
        return {}

    counts: Dict[str, int] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or (len(line) == 40 and all(c in "0123456789abcdef" for c in line)):
            continue  # commit hash line
        if line.endswith(".py"):
            key = line.replace(os.sep, "/")
            counts[key] = counts.get(key, 0) + 1
    return counts


def apply_churn(G: nx.DiGraph, project_root: str) -> bool:
    """Attach a per-node ``churn`` attribute from git history.

    Returns True if any non-zero churn was applied.
    """
    counts = git_churn(project_root)
    if not counts:
        return False
    top = _toplevel(project_root) or project_root
    applied = False
    for node in G.nodes():
        path = G.nodes[node].get("path", "")
        if not path:
            continue
        rel = os.path.relpath(os.path.abspath(path), top).replace(os.sep, "/")
        churn = counts.get(rel, 0)
        G.nodes[node]["churn"] = churn
        if churn:
            applied = True
    return applied
