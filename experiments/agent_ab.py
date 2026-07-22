"""Track B — the agent A/B pilot: prep and grading.

Two arms per issue, identical in every respect except one:

* **control**   — the repository and the issue text. That's it.
* **pack**      — the same, plus a `py-code-visualizer context` pack prepended.

This module does **not** run the agents. It prepares an isolated working copy per
run and, afterwards, grades whatever the agent left behind by running the
project's own tests: FAIL_TO_PASS must flip fail→pass, PASS_TO_PASS must stay
green. The agent runs themselves are driven by cold Claude Code subagents (the
headless CLI is unusable here — it reports "Credit balance is too low").

Protocol, following SWE-bench: the agent never sees the gold ``patch``, the
``test_patch`` (which names the answer tests), or ``hints_text``. The test patch
is applied only at grading time, on top of whatever the agent wrote.

Usage:
    python -m experiments.agent_ab select          # pre-registered sample
    python -m experiments.agent_ab prep  <id> <arm>
    python -m experiments.agent_ab grade <id> <arm>
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from experiments import dataset, envspec, repos, seeds
from pyvisualizer.api import build_graph
from pyvisualizer.context import build_context_pack, render_pack_markdown

# Isolated from the Track A checkouts so the two tracks can run concurrently.
WORK_ROOT = os.environ.get(
    "PYVIS_EXP_WORKROOT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "agent_runs"),
)
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

ARMS = ("control", "pack")

# Repos whose test suite we can actually drive here (no Docker). sympy is excluded
# on purpose: it uses a bespoke runner and bare test-function ids, and a wrong
# harness would look like an agent failure. Decided before any results were seen.
PILOT_REPOS = {
    "django/django",
    "sphinx-doc/sphinx",
    "pytest-dev/pytest",
    "pylint-dev/pylint",
    "psf/requests",
    "mwaskom/seaborn",
    "pallets/flask",
}
PILOT_DIFFICULTY = {"<15 min fix", "15 min - 1 hour"}

_DJANGO_TEST_RE = re.compile(r"^(\w+) \(([\w.]+)\)$")


# --------------------------------------------------------------------------- #
# Pre-registered instance selection
# --------------------------------------------------------------------------- #
def select_pilot(n: int = 8, seed: int = 1998) -> List[Dict[str, Any]]:
    """Deterministic, repo-stratified sample. Fixed before any agent run.

    Plain random sampling returns all-django (231 of the ~296 eligible instances
    are django), which would make the pilot a study of one codebase. We instead
    take instances round-robin across repos, so a result isn't an artifact of a
    single project's layout.
    """
    data = [
        d
        for d in dataset.load()
        if d["repo"] in PILOT_REPOS and d.get("difficulty") in PILOT_DIFFICULTY
    ]
    by_repo: Dict[str, List[Dict[str, Any]]] = {}
    for d in data:
        by_repo.setdefault(d["repo"], []).append(d)

    rng = random.Random(seed)
    pools = {}
    for repo in sorted(by_repo):
        items = sorted(by_repo[repo], key=lambda d: d["instance_id"])
        rng.shuffle(items)
        pools[repo] = items

    picked: List[Dict[str, Any]] = []
    order = sorted(pools)
    while len(picked) < n and any(pools[r] for r in order):
        for repo in order:
            if pools[repo] and len(picked) < n:
                picked.append(pools[repo].pop())
    return sorted(picked, key=lambda d: d["instance_id"])


def _instance(instance_id: str) -> Dict[str, Any]:
    for d in dataset.load():
        if d["instance_id"] == instance_id:
            return d
    raise SystemExit(f"unknown instance: {instance_id}")


def run_dir(instance_id: str, arm: str) -> str:
    return os.path.join(WORK_ROOT, f"{instance_id}__{arm}")


# --------------------------------------------------------------------------- #
# Prep
# --------------------------------------------------------------------------- #
def _force_remove(func: Any, path: str, _exc: Any) -> None:
    """Virtualenvs contain read-only files; make them writable and retry."""
    os.chmod(path, 0o700)
    func(path)


def _local_clone(repo: str, commit: str, dest: str) -> None:
    """Clone from the local cache so each arm is fully isolated on disk."""
    src = repos.ensure_full_clone(repo)
    if os.path.exists(dest):
        shutil.rmtree(dest, onerror=_force_remove)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    subprocess.run(
        ["git", "clone", "--no-checkout", "--local", src, dest], check=True, capture_output=True
    )
    proc = subprocess.run(
        ["git", "checkout", "-f", commit], cwd=dest, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"checkout {repo}@{commit} failed: {proc.stderr[-300:]}")
    # A clean baseline so `git diff` afterwards is exactly the agent's work.
    subprocess.run(["git", "clean", "-qfdx"], cwd=dest, capture_output=True)


def build_pack(
    repo: str, path: str, problem_statement: str, budget_tokens: int = 4000
) -> Tuple[str, List[str]]:
    """The treatment: a verified context pack seeded from the issue text alone."""
    src_root = repos.source_root(repo, path)
    result = build_graph(src_root)
    seed_nodes = seeds.derive_seeds(problem_statement, result.graph)
    if not seed_nodes:
        return "", []
    pack = build_context_pack(result, focus=seed_nodes, budget_tokens=budget_tokens)
    return render_pack_markdown(pack), seed_nodes


_TASK_TEMPLATE = """# Task

You are working in a checkout of `{repo}` at commit `{commit}`.
Repository root: `{path}`

Fix the issue described below by editing the source. Do not write new tests —
the project's existing test suite will be used to check your work.

## Issue

{problem_statement}
{pack_section}
## Notes

- Work only inside `{path}`.
- Make the smallest correct change that fixes the issue.
- When you are done, leave your changes in the working tree (do not commit).
"""

_PACK_SECTION = """
## Verified architecture context

The following was generated by static analysis of this exact checkout
(`py-code-visualizer context`). Every function and call edge below is parsed from
the AST with `file:line` provenance — it is ground truth about this codebase, not
a guess. Use it to find the relevant code instead of searching from scratch.

{pack}
"""


def prep(instance_id: str, arm: str, budget_tokens: int = 4000) -> Dict[str, Any]:
    inst = _instance(instance_id)
    dest = run_dir(instance_id, arm)
    _local_clone(inst["repo"], inst["base_commit"], dest)

    pack_md: str = ""
    seed_nodes: List[str] = []
    if arm == "pack":
        pack_md, seed_nodes = build_pack(
            inst["repo"], dest, inst["problem_statement"], budget_tokens
        )

    task = _TASK_TEMPLATE.format(
        repo=inst["repo"],
        commit=inst["base_commit"],
        path=dest,
        problem_statement=inst["problem_statement"],
        pack_section=_PACK_SECTION.format(pack=pack_md) if pack_md else "",
    )
    task_path = os.path.join(WORK_ROOT, f"{instance_id}__{arm}.task.md")
    with open(task_path, "w", encoding="utf-8") as f:
        f.write(task)

    meta = {
        "instance_id": instance_id,
        "arm": arm,
        "repo": inst["repo"],
        "base_commit": inst["base_commit"],
        "path": dest,
        "task_file": task_path,
        "seeds": seed_nodes,
        "pack_chars": len(pack_md),
        "task_chars": len(task),
    }
    with open(
        os.path.join(WORK_ROOT, f"{instance_id}__{arm}.meta.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(meta, f, indent=2)
    return meta


# --------------------------------------------------------------------------- #
# Grading — run the project's real tests
# --------------------------------------------------------------------------- #
def _base_interpreter() -> str:
    """The Python to build test venvs with — old enough to run these snapshots.

    SWE-bench Verified is drawn from 2020-2023, and modern Python has removed
    APIs those releases rely on (e.g. Python 3.14 dropped ``pkgutil.get_loader``,
    which Flask 2.3 calls — so a perfectly good checkout dies at import time).
    Prefer an older interpreter; override with ``PYVIS_EXP_PYTHON``.
    """
    override = os.environ.get("PYVIS_EXP_PYTHON")
    if override:
        return override
    for candidate in ("/usr/bin/python3", "python3.11", "python3.10", "python3.9"):
        path = candidate if os.path.isabs(candidate) else shutil.which(candidate) or ""
        if path and os.path.exists(path):
            return path
    return sys.executable


def _venv_python(workdir: str) -> str:
    venv = os.path.join(workdir, ".exp_venv")
    py = os.path.join(venv, "bin", "python")
    if not os.path.exists(py):
        subprocess.run([_base_interpreter(), "-m", "venv", venv], check=True, capture_output=True)
        subprocess.run(
            [py, "-m", "pip", "-q", "install", "-U", "pip", "setuptools", "wheel"],
            capture_output=True,
        )
    return py


def _install(workdir: str, py: str, repo: str, version: str) -> str:
    """Install the project, then overlay SWE-bench's pinned dependency set.

    Order matters. The editable install goes first *with* its dependencies —
    django needs ``asgiref``, requests needs ``urllib3``, pytest needs ``toml``,
    and none of those appear in SWE-bench's ``pip_packages`` because its Docker
    images already have them. The pins go on top afterwards so that where the two
    disagree (e.g. ``Werkzeug==2.3.7``), SWE-bench's version is the one that
    survives.
    """
    notes: List[str] = []

    proc = subprocess.run(
        [py, "-m", "pip", "-q", "install", "-e", "."],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=2400,
    )
    notes.append(
        "editable" if proc.returncode == 0 else f"editable-failed:{proc.stderr.strip()[-150:]}"
    )

    pins = envspec.pip_packages(repo, version)
    if pins:
        dep = subprocess.run(
            [py, "-m", "pip", "-q", "install", *pins],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=2400,
        )
        notes.append(
            "pins-ok" if dep.returncode == 0 else f"pins-failed:{dep.stderr.strip()[-150:]}"
        )
    else:
        notes.append("no-pins")
    return " | ".join(notes)


def _reset_test_files(workdir: str, test_patch: str) -> None:
    """Restore every path the test patch touches back to the base commit.

    The agent is told not to write tests, but it might anyway, and a previous
    grading pass will have left the patch applied. Either way the answer key must
    land on a pristine test tree or `git apply` fails for the wrong reason.
    """
    paths = {m[1] for m in re.findall(r"^diff --git a/(\S+) b/(\S+)$", test_patch, re.MULTILINE)}
    for path in sorted(paths):
        restored = subprocess.run(
            ["git", "checkout", "HEAD", "--", path], cwd=workdir, capture_output=True, text=True
        )
        if restored.returncode != 0:
            # Not in HEAD → the patch creates it; make sure it isn't there.
            target = os.path.join(workdir, path)
            if os.path.exists(target):
                os.remove(target)


def _django_test_id(raw: str) -> str:
    """`test_x (module.Class)` → `module.Class.test_x`, which runtests.py accepts."""
    m = _DJANGO_TEST_RE.match(raw.strip())
    return f"{m.group(2)}.{m.group(1)}" if m else raw.strip()


def _test_command(repo: str, py: str, tests: List[str]) -> Tuple[List[str], Optional[str]]:
    if repo == "django/django":
        return (
            [py, "tests/runtests.py", "--settings=test_sqlite", "--verbosity=1"]
            + [_django_test_id(t) for t in tests],
            None,
        )
    return ([py, "-m", "pytest", "-x", "-q", "--no-header"] + tests, None)


def _run_tests(
    workdir: str, repo: str, py: str, tests: List[str], timeout: int = 1800
) -> Dict[str, Any]:
    if not tests:
        return {"ran": 0, "passed": True, "output": "(no tests specified)"}
    cmd, _ = _test_command(repo, py, tests)
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout + proc.stderr)[-4000:]
        return {
            "ran": len(tests),
            "passed": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": out,
        }
    except subprocess.TimeoutExpired:
        return {"ran": len(tests), "passed": False, "returncode": -1, "output": "TIMEOUT"}


def grade(instance_id: str, arm: str) -> Dict[str, Any]:
    """Apply the held-out test patch, then run FAIL_TO_PASS and PASS_TO_PASS."""
    inst = _instance(instance_id)
    workdir = run_dir(instance_id, arm)
    if not os.path.isdir(workdir):
        raise SystemExit(f"no working copy at {workdir}; run prep first")

    diff = subprocess.run(["git", "diff"], cwd=workdir, capture_output=True, text=True).stdout
    changed = subprocess.run(
        ["git", "diff", "--name-only"], cwd=workdir, capture_output=True, text=True
    ).stdout.split()

    py = _venv_python(workdir)
    install_mode = _install(workdir, py, inst["repo"], str(inst.get("version", "")))

    # Restore the test files to their pristine state first, so grading is
    # idempotent — re-grading a run must not fail because a previous grade
    # already applied the same patch.
    _reset_test_files(workdir, inst["test_patch"])

    # The answer key goes in only now, never before the agent ran.
    patch_file = os.path.join(workdir, ".test_patch.diff")
    with open(patch_file, "w", encoding="utf-8") as f:
        f.write(inst["test_patch"])
    applied = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", patch_file],
        cwd=workdir,
        capture_output=True,
        text=True,
    )

    f2p = dataset.parse_test_list(inst["FAIL_TO_PASS"])
    p2p = dataset.parse_test_list(inst["PASS_TO_PASS"])
    f2p_res = _run_tests(workdir, inst["repo"], py, f2p)
    p2p_res = _run_tests(workdir, inst["repo"], py, p2p)

    resolved = bool(f2p_res["passed"] and p2p_res["passed"] and applied.returncode == 0)
    record = {
        "instance_id": instance_id,
        "arm": arm,
        "repo": inst["repo"],
        "resolved": resolved,
        "test_patch_applied": applied.returncode == 0,
        "install_mode": install_mode,
        "fail_to_pass": f2p_res,
        "pass_to_pass": p2p_res,
        "files_changed": changed,
        "diff_chars": len(diff),
        "made_any_change": bool(diff.strip()),
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(
        os.path.join(WORK_ROOT, f"{instance_id}__{arm}.grade.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(record, f, indent=2)
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("-n", type=int, default=8)
    p = sub.add_parser("prep")
    p.add_argument("instance_id")
    p.add_argument("arm", choices=ARMS)
    g = sub.add_parser("grade")
    g.add_argument("instance_id")
    g.add_argument("arm", choices=ARMS)
    args = ap.parse_args()

    os.makedirs(WORK_ROOT, exist_ok=True)
    if args.cmd == "select":
        for inst in select_pilot(args.n):
            print(f"{inst['instance_id']:40s} {inst['repo']:20s} {inst.get('difficulty', '')}")
    elif args.cmd == "prep":
        print(json.dumps(prep(args.instance_id, args.arm), indent=2))
    else:
        print(json.dumps(grade(args.instance_id, args.arm), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
