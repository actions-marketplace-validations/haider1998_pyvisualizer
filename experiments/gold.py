"""Ground truth: which files and functions did the real fix actually touch?

The oracle is the ``patch`` field — the diff that was reviewed and merged by the
project's own maintainers. We parse it for the **old-side** line ranges (the
graph is built at ``base_commit``, i.e. before the fix) and intersect those with
each function's ``[lineno, end_lineno]`` span.

Test files are excluded: SWE-bench's gold patch is the source fix, and asking a
retrieval system to "find the test that will be written" is not a fair question.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

import networkx as nx

from pyvisualizer.changes import map_lines_to_functions

# "@@ -oldstart,oldcount +newstart,newcount @@" — we want the old side.
_HUNK_OLD_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
_DIFF_FILE_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)")

LineRange = Tuple[int, int]


def _is_test_path(path: str) -> bool:
    parts = path.replace(os.sep, "/").split("/")
    base = parts[-1]
    return (
        base.startswith("test_")
        or base.endswith("_test.py")
        or base == "conftest.py"
        or any(p in {"tests", "test", "testing"} for p in parts[:-1])
    )


@dataclass
class GoldTruth:
    files: Set[str] = field(default_factory=set)
    line_ranges: Dict[str, List[LineRange]] = field(default_factory=dict)
    functions: List[str] = field(default_factory=list)

    @property
    def has_functions(self) -> bool:
        return bool(self.functions)


def parse_patch(patch: str, *, python_only: bool = True) -> GoldTruth:
    """Extract the changed files and their old-side line ranges from a diff."""
    truth = GoldTruth()
    current: str = ""
    for line in patch.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            path = m.group(2)
            keep = not _is_test_path(path) and (path.endswith(".py") or not python_only)
            current = path if keep else ""
            if current:
                truth.files.add(current)
                truth.line_ranges.setdefault(current, [])
            continue
        if not current:
            continue
        hm = _HUNK_OLD_RE.match(line)
        if hm:
            start = int(hm.group(1))
            count = int(hm.group(2)) if hm.group(2) is not None else 1
            # A pure insertion (count == 0) has no old-side extent; anchor it at
            # the insertion point so it still maps to the enclosing function.
            end = start + count - 1 if count > 0 else start
            truth.line_ranges[current].append((start, max(start, end)))
    return truth


def resolve_functions(truth: GoldTruth, G: nx.DiGraph, project_root: str) -> GoldTruth:
    """Map the gold line ranges onto call-graph nodes (reuses the review engine)."""
    truth.functions = map_lines_to_functions(G, truth.line_ranges, project_root)
    return truth


def gold_for_instance(instance: Dict[str, str], G: nx.DiGraph, project_root: str) -> GoldTruth:
    truth = parse_patch(instance["patch"])
    return resolve_functions(truth, G, project_root)
