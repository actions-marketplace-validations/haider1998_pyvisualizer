"""Clone the real repositories and check them out at each issue's base commit.

Blobless partial clones (``--filter=blob:none``) keep this tractable: full
history for repos like django/sympy is hundreds of megabytes, and we only ever
need the trees at a handful of commits.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
REPOS_DIR = os.path.join(CACHE_DIR, "repos")


def _run(
    args: List[str], cwd: Optional[str] = None, timeout: int = 1800
) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def repo_dir(repo: str) -> str:
    return os.path.join(REPOS_DIR, repo.replace("/", "__"))


def ensure_clone(repo: str) -> str:
    """Clone ``owner/name`` once (blobless); return the working-copy path."""
    dest = repo_dir(repo)
    if os.path.isdir(os.path.join(dest, ".git")):
        return dest
    os.makedirs(REPOS_DIR, exist_ok=True)
    proc = _run(
        [
            "git",
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            f"https://github.com/{repo}.git",
            dest,
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(f"clone failed for {repo}: {proc.stderr[-500:]}")
    return dest


FULL_REPOS_DIR = os.path.join(CACHE_DIR, "repos_full")


def ensure_full_clone(repo: str) -> str:
    """A complete (non-partial) mirror, used as the source for agent-run clones.

    The Track A cache is a blobless partial clone, which is ideal for streaming
    through hundreds of commits. But ``git clone --local`` from a partial clone
    produces a repository whose promisor remote is that local path, so checking
    out a commit fails: the blobs live on GitHub, and the new clone has no way to
    reach them. Agent runs therefore branch from a full mirror instead, where
    ``--local`` hardlinks everything needed.
    """
    dest = os.path.join(FULL_REPOS_DIR, repo.replace("/", "__") + ".git")
    if os.path.isdir(dest):
        return dest
    os.makedirs(FULL_REPOS_DIR, exist_ok=True)
    proc = _run(["git", "clone", "--bare", f"https://github.com/{repo}.git", dest], timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"full clone failed for {repo}: {proc.stderr[-500:]}")
    return dest


def checkout(repo: str, commit: str) -> str:
    """Hard-checkout ``commit``; returns the path. Fetches the object if needed."""
    dest = ensure_clone(repo)
    proc = _run(["git", "checkout", "-f", commit], cwd=dest)
    if proc.returncode != 0:
        fetched = _run(["git", "fetch", "--filter=blob:none", "origin", commit], cwd=dest)
        if fetched.returncode != 0:
            raise RuntimeError(f"fetch failed for {repo}@{commit}: {fetched.stderr[-300:]}")
        proc = _run(["git", "checkout", "-f", commit], cwd=dest)
        if proc.returncode != 0:
            raise RuntimeError(f"checkout failed for {repo}@{commit}: {proc.stderr[-300:]}")
    _run(["git", "clean", "-qfdx"], cwd=dest)
    return dest


def source_root(repo: str, path: str) -> str:
    """The directory actually worth analyzing (skip docs/, tooling, fixtures).

    Analyzing the whole checkout would pull in each project's own test suite and
    doc build scripts, which are not what the issue is about and would distort
    both the graph and the BM25 baseline — equally, but noisily.
    """
    package = {
        "django/django": "django",
        "sympy/sympy": "sympy",
        "sphinx-doc/sphinx": "sphinx",
        "pylint-dev/pylint": "pylint",
        "pytest-dev/pytest": "src",
        "psf/requests": "requests",
        "pallets/flask": "src",
        "mwaskom/seaborn": "seaborn",
        "matplotlib/matplotlib": "lib",
        "scikit-learn/scikit-learn": "sklearn",
        "astropy/astropy": "astropy",
        "pydata/xarray": "xarray",
    }.get(repo)
    if package:
        candidate = os.path.join(path, package)
        if os.path.isdir(candidate):
            return candidate
    return path
