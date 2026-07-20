"""
``init`` — opt-in onboarding.

The point of this command is restraint: a user who wants only PR reviews should
not be handed context packs, README automation, and CI gates they never asked
for. ``init`` presents the four automations, generates *only* the ones chosen,
never overwrites existing files without ``--force``, and never rewrites an
existing ``[tool.pyvisualizer]`` table — it records the chosen profile so future
runs (and future features) respect the decision instead of piling on.

Profiles map to the two jobs:
- ``review`` / ``gates`` → Job 1 (code review).
- ``context`` → Job 2 (agent context); also writes the AGENTS.md wiring.
- ``readme`` → a self-healing diagram (Job 1, documentation).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("pyvisualizer.init")

_ALL = ["review", "readme", "context", "gates"]
_DESC = {
    "review": "PR review reports — what changed, blast radius, risk flags (Job 1)",
    "readme": "Self-healing architecture diagram committed to your README",
    "context": "Verified context packs + AGENTS.md wiring for AI agents (Job 2)",
    "gates": "CI gate: fail the build on new cycles / layer violations",
}


# --------------------------------------------------------------------------- #
# CI workflow generators
# --------------------------------------------------------------------------- #
def _gh(name: str, body: str) -> str:
    return body.lstrip("\n")


_GH_REVIEW = """
name: Architecture review
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.x'
      - run: pip install py-code-visualizer
      - name: Generate architecture review
        run: py-code-visualizer review . --base "origin/${{ github.base_ref }}" -o review.md
      - name: Post review comment
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const body = fs.readFileSync('review.md', 'utf8');
            await github.rest.issues.createComment({
              ...context.repo, issue_number: context.issue.number, body
            });
"""

_GH_README = """
name: Self-healing architecture diagram
on:
  push:
    branches: [ main, master ]
permissions:
  contents: write
jobs:
  readme:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.x'
      - run: pip install py-code-visualizer
      - run: py-code-visualizer readme .
      - name: Commit if the architecture changed
        run: |
          if ! git diff --quiet; then
            git config user.name "pyvisualizer-bot"
            git config user.email "bot@users.noreply.github.com"
            git commit -am "docs: refresh architecture diagram [skip ci]"
            git push
          fi
"""

_GH_CONTEXT = """
name: Architecture context freshness
on: pull_request
jobs:
  context:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.x'
      - run: pip install py-code-visualizer
      - name: Fail if ARCHITECTURE.json / AGENTS.md are stale
        run: py-code-visualizer export . --check
"""

_GH_GATES = """
name: Architecture gate
on: pull_request
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.x'
      - run: pip install py-code-visualizer
      - run: py-code-visualizer check . --fail-on-cycles
"""

_GH_FILES = {
    "review": (".github/workflows/pyvisualizer-review.yml", _GH_REVIEW),
    "readme": (".github/workflows/pyvisualizer-readme.yml", _GH_README),
    "context": (".github/workflows/pyvisualizer-context.yml", _GH_CONTEXT),
    "gates": (".github/workflows/pyvisualizer-check.yml", _GH_GATES),
}

_GITLAB_JOBS = {
    "review": (
        "pyvisualizer-review:\n"
        "  image: python:3\n"
        "  script:\n"
        "    - pip install py-code-visualizer\n"
        '    - py-code-visualizer review . --base "origin/$CI_MERGE_REQUEST_TARGET_BRANCH_NAME"\n'
        "  rules:\n"
        "    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'\n"
    ),
    "context": (
        "pyvisualizer-context:\n"
        "  image: python:3\n"
        "  script:\n"
        "    - pip install py-code-visualizer\n"
        "    - py-code-visualizer export . --check\n"
    ),
    "gates": (
        "pyvisualizer-check:\n"
        "  image: python:3\n"
        "  script:\n"
        "    - pip install py-code-visualizer\n"
        "    - py-code-visualizer check . --fail-on-cycles\n"
    ),
    "readme": (
        "# 'readme' auto-commits a diagram; run it from a scheduled/main pipeline\n"
        "# with a token that can push, e.g.:\n"
        "pyvisualizer-readme:\n"
        "  image: python:3\n"
        "  script:\n"
        "    - pip install py-code-visualizer\n"
        "    - py-code-visualizer readme .\n"
    ),
}


# --------------------------------------------------------------------------- #
# Planning + writing
# --------------------------------------------------------------------------- #
def _plan_files(features: List[str], ci: str) -> List[Tuple[str, str]]:
    """Return the (relative_path, content) files to create for the selection."""
    files: List[Tuple[str, str]] = []
    if ci == "github":
        for feat in features:
            rel, body = _GH_FILES[feat]
            files.append((rel, _gh(rel, body)))
    elif ci == "gitlab":
        jobs = "\n".join(_GITLAB_JOBS[f] for f in features)
        header = (
            "# Generated by `py-code-visualizer init`. Include this file from .gitlab-ci.yml.\n\n"
        )
        files.append(("pyvisualizer.gitlab-ci.yml", header + jobs))
    return files


def _write_file(root: str, rel: str, content: str, force: bool) -> str:
    full = os.path.join(root, rel)
    if os.path.exists(full) and not force:
        return "skip"
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    existed = os.path.exists(full)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return "overwrite" if existed else "write"


def _record_features(root: str, features: List[str]) -> Optional[str]:
    """Record ``features`` in pyproject; return a manual-add hint if we couldn't.

    Never rewrites an existing ``[tool.pyvisualizer]`` table — if one exists we
    return the line for the user to add themselves rather than risk mangling it.
    """
    from pyvisualizer.config import find_pyproject

    line = "features = [" + ", ".join(f'"{f}"' for f in features) + "]"
    pyproject = find_pyproject(root)
    if not pyproject:
        target = os.path.join(root, "pyproject.toml")
        with open(target, "a", encoding="utf-8") as f:
            f.write(f"\n[tool.pyvisualizer]\n{line}\n")
        return None
    with open(pyproject, "r", encoding="utf-8") as f:
        content = f.read()
    if "[tool.pyvisualizer]" in content:
        return f"Add under [tool.pyvisualizer] in {os.path.basename(pyproject)}:  {line}"
    with open(pyproject, "a", encoding="utf-8") as f:
        f.write(f"\n[tool.pyvisualizer]\n{line}\n")
    return None


# --------------------------------------------------------------------------- #
# Local one-time actions (beyond CI files)
# --------------------------------------------------------------------------- #
def _action_readme(root: str) -> str:
    from pyvisualizer import __version__
    from pyvisualizer.api import build_graph
    from pyvisualizer.inject import update_file
    from pyvisualizer.metrics import compute_health
    from pyvisualizer.visualizers.mermaid import generate_github_mermaid

    result = build_graph(root)
    code = generate_github_mermaid(result.graph, detail="module")
    health = compute_health(result.graph)
    heading = (
        f"*{result.num_nodes} functions · {result.num_edges} calls · "
        f"health {health.grade} ({health.score}/100) — detail: module*"
    )
    footer = (
        "<sub>🔒 Deterministic, AST-verified — no code executed. "
        "Generated by py-code-visualizer.</sub>"
    )
    _ = __version__
    changed = update_file(os.path.join(root, "README.md"), code, heading=heading, footer=footer)
    return "README.md updated" if changed else "README.md already current"


def _action_context(root: str) -> str:
    from pyvisualizer import __version__
    from pyvisualizer.api import build_graph
    from pyvisualizer.export import export_for_ai

    result = build_graph(root)
    export_for_ai(result, out_dir=root, tool_version=__version__, agents_md=True)
    return "ARCHITECTURE.json/.md + AGENTS.md written"


_ACTIONS: Dict[str, Callable[[str], str]] = {
    "readme": _action_readme,
    "context": _action_context,
}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def _parse_features(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    out: List[str] = []
    for tok in raw.replace(",", " ").split():
        tok = tok.strip().lower()
        if tok in _ALL and tok not in out:
            out.append(tok)
    return out


def _prompt() -> List[str]:
    print("py-code-visualizer init — choose the automation you want:\n")
    for i, feat in enumerate(_ALL, 1):
        print(f"  {i}. {feat:<8} {_DESC[feat]}")
    print("\nEnter numbers or names (comma-separated), or blank to cancel.")
    try:
        raw = input("> ").strip()
    except EOFError:
        return []
    chosen: List[str] = []
    for tok in raw.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= len(_ALL):
            feat = _ALL[int(tok) - 1]
        else:
            feat = tok.lower()
        if feat in _ALL and feat not in chosen:
            chosen.append(feat)
    return chosen


def run_init(
    path: str,
    features: Optional[str] = None,
    ci: str = "github",
    list_only: bool = False,
    force: bool = False,
) -> int:
    root = os.path.abspath(path)

    if list_only:
        print("py-code-visualizer init — available profiles:\n")
        for feat in _ALL:
            print(f"  {feat:<8} {_DESC[feat]}")
            if ci == "github":
                print(f"           creates: {_GH_FILES[feat][0]}")
        if ci == "gitlab":
            print("\n  (gitlab) creates: pyvisualizer.gitlab-ci.yml with the chosen jobs")
        for feat in ("readme", "context"):
            print(f"  {feat}: also runs once locally to produce its artifacts")
        print("\nRun again with --with review,context (etc.) to generate. Nothing was written.")
        return 0

    selected = _parse_features(features)
    if not selected and features is None and sys.stdin.isatty():
        selected = _prompt()
    if not selected:
        logger.error("No automations selected. Use --with review,readme,context,gates (or --list).")
        return 1

    # 1) CI files.
    results: List[str] = []
    for rel, content in _plan_files(selected, ci):
        status = _write_file(root, rel, content, force)
        verb = {"write": "created", "overwrite": "overwrote", "skip": "exists (skipped)"}[status]
        results.append(f"  {verb}: {rel}")

    # 2) Local one-time actions.
    for feat in selected:
        action = _ACTIONS.get(feat)
        if action:
            try:
                results.append(f"  {action(root)}")
            except Exception as e:  # pragma: no cover - defensive
                results.append(f"  (skipped {feat} action: {e})")

    # 3) Record the profile.
    hint = _record_features(root, selected)

    print(f"Set up: {', '.join(selected)}  (CI: {ci})")
    for line in results:
        print(line)
    if hint:
        print(hint)
    print("\nUse --force to overwrite files that already existed.")
    return 0
