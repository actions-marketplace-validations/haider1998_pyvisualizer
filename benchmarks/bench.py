"""
Reproducible benchmark + validation harness.

Runs the *real* tool over two inputs — py-code-visualizer's own source, and a
deterministic ~100k-line synthetic project — and records honest, reproducible
numbers into ``docs/benchmarks.json``:

* time-to-graph and functions/sec,
* the confidence breakdown (resolved / inherited / ambiguous),
* provenance coverage (% of edges carrying a ``file:line``),
* a double-run SHA-256 proof that the canonical JSON is byte-identical,
* zero-network-request proof for the generated HTML viewer,
* the git commit and hardware the numbers were measured on.

Every number the website and docs display is read from the JSON this writes;
nothing is hand-typed. Re-run with ``python -m benchmarks.bench``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from benchmarks.genproject import generate
from pyvisualizer import __version__ as _pkg_version_fallback
from pyvisualizer.api import build_graph
from pyvisualizer.serializers.json_graph import graph_to_json
from pyvisualizer.visualizers.html import generate_html_visualization

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Matches an actual external resource load (src=/href= pointing at http(s)).
# Deliberately does NOT match SVG xmlns="http://www.w3.org/..." namespaces,
# which are declarations, not network requests.
_EXTERNAL_RE = re.compile(r"""(?:src|href)\s*=\s*["']https?://""", re.IGNORECASE)


def _tool_version() -> str:
    try:
        return str(_pkg_version_fallback)
    except Exception:
        return ""


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def _hardware() -> Dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
    }


def _peak_rss_mb() -> Optional[float]:
    try:
        import resource

        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is bytes on macOS, kilobytes on Linux.
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return round(maxrss / divisor, 1)
    except Exception:
        return None


def _time_build(path: str, repeats: int) -> Dict[str, Any]:
    """Build the graph ``repeats`` times; report the fastest wall time."""
    best = float("inf")
    result = None
    for _ in range(repeats):
        t = time.perf_counter()
        result = build_graph(path)
        dt = time.perf_counter() - t
        best = min(best, dt)
    assert result is not None
    return {"seconds": best, "result": result}


def _confidence_stats(result: Any) -> Dict[str, Any]:
    G = result.graph
    conf = Counter(d.get("confidence", "resolved") for _, _, d in G.edges(data=True))
    with_prov = sum(1 for _, _, d in G.edges(data=True) if d.get("file"))
    total_edges = G.number_of_edges()
    return {
        "resolved": conf.get("resolved", 0),
        "inherited": conf.get("inherited", 0),
        "ambiguous": conf.get("ambiguous", 0),
        "edges_with_provenance": with_prov,
        "provenance_pct": round(100.0 * with_prov / total_edges, 2) if total_edges else 100.0,
    }


def _determinism_proof(path: str) -> Dict[str, Any]:
    """Build + serialize twice; prove the canonical JSON is byte-identical."""
    hashes: List[str] = []
    for _ in range(2):
        r = build_graph(path)
        payload = graph_to_json(
            r.graph,
            project_name=r.project_name,
            project_root=r.project_root,
            tool_version="",  # pin so the hash reflects the graph, not the version
        )
        hashes.append(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    return {
        "sha256_run1": hashes[0],
        "sha256_run2": hashes[1],
        "byte_identical": hashes[0] == hashes[1],
    }


def _html_network_proof(path: str) -> Dict[str, Any]:
    """Generate the HTML viewer and count real external resource references."""
    r = build_graph(path)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "viewer.html")
        generate_html_visualization(
            r.graph, out, project_name=r.project_name, project_root=r.project_root
        )
        with open(out, "r", encoding="utf-8") as f:
            doc = f.read()
    external = _EXTERNAL_RE.findall(doc)
    return {
        "external_requests": len(external),
        "self_contained": len(external) == 0,
        "size_kb": round(len(doc.encode("utf-8")) / 1024, 1),
    }


def _context_stats(result: Any) -> Dict[str, Any]:
    """Measure a task-scoped context pack vs. feeding the whole source.

    This is the Job-2 optimization number, measured for the realistic case: an
    agent working on **one** function gets a small verified pack (that function,
    its callers/callees, and PageRank-selected relevant neighbors under a token
    budget) instead of the entire codebase. Focus is the single highest-degree
    node — deterministic — standing in for "a central function to change."
    """
    from pyvisualizer.context import build_context_pack

    G = result.graph
    if G.number_of_nodes() == 0:
        return {"reduction_pct": 0.0, "note": "empty graph"}
    focus = sorted(G.nodes(), key=lambda n: (-G.degree(n), n))[0]
    pack = build_context_pack(result, focus=[focus], budget_tokens=4000)
    return {
        "focus": focus,
        "included_functions": len(pack.included),
        "total_functions": G.number_of_nodes(),
        "estimated_pack_tokens": pack.est_pack_tokens,
        "estimated_full_source_tokens": pack.est_full_tokens,
        "reduction_pct": pack.reduction_pct,
        "note": "estimate, chars/4; pack focused on one function, 4000-token budget",
    }


def _bench_target(name: str, path: str, repeats: int) -> Dict[str, Any]:
    timing = _time_build(path, repeats)
    result = timing["result"]
    seconds = timing["seconds"]
    nodes = result.num_nodes
    edges = result.num_edges
    kloc = _count_lines(path)
    entry = {
        "name": name,
        "files": len(result.files),
        "lines": kloc,
        "functions": nodes,
        "calls": edges,
        "seconds": round(seconds, 4),
        "ms": round(seconds * 1000, 1),
        "functions_per_sec": round(nodes / seconds) if seconds > 0 else None,
        "lines_per_sec": round(kloc / seconds) if seconds > 0 and kloc else None,
        "confidence": _confidence_stats(result),
        "context_pack": _context_stats(result),
        "determinism": _determinism_proof(path),
        "html": _html_network_proof(path),
    }
    return entry


def _count_lines(path: str) -> int:
    total = 0
    if os.path.isfile(path):
        paths = [path]
    else:
        paths = []
        for root, _dirs, files in os.walk(path):
            for fn in files:
                if fn.endswith(".py"):
                    paths.append(os.path.join(root, fn))
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                total += sum(1 for _ in f)
        except OSError:
            continue
    return total


def run(target_lines: int = 100_000, repeats: int = 3, seed: int = 1998) -> Dict[str, Any]:
    targets: List[Dict[str, Any]] = []

    # 1) The tool on its own source — the "dogfood" number.
    self_src = os.path.join(REPO_ROOT, "pyvisualizer")
    targets.append(_bench_target("py-code-visualizer (self)", self_src, repeats))

    # 2) The deterministic synthetic monolith.
    with tempfile.TemporaryDirectory() as td:
        proj = os.path.join(td, "genproj_bench")
        gen = generate(proj, seed=seed, target_lines=target_lines)
        targets.append(_bench_target(f"synthetic monolith (~{target_lines:,} LOC)", proj, repeats))
        synthetic_meta = {"seed": gen["seed"], "modules": gen["modules"], "layers": gen["layers"]}

    report = {
        "generated_with": "benchmarks/bench.py",
        "note": "Reproduce: python -m benchmarks.bench",
        "commit": _git_commit(),
        "tool_version": _tool_version(),
        "measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hardware": _hardware(),
        "peak_rss_mb": _peak_rss_mb(),
        "synthetic": synthetic_meta,
        "targets": targets,
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark py-code-visualizer and emit docs JSON.")
    ap.add_argument("--target-lines", type=int, default=100_000)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1998)
    ap.add_argument(
        "--out",
        default=os.path.join(REPO_ROOT, "docs", "benchmarks.json"),
        help="Where to write the report (default: docs/benchmarks.json).",
    )
    ap.add_argument("--print", action="store_true", help="Also print the report to stdout.")
    args = ap.parse_args()

    report = run(target_lines=args.target_lines, repeats=args.repeats, seed=args.seed)

    # Fail loudly if any core invariant did not hold — a benchmark that quietly
    # records a determinism break would be worse than useless.
    for t in report["targets"]:
        if not t["determinism"]["byte_identical"]:
            print(
                f"INVARIANT VIOLATION: {t['name']} not byte-identical across runs", file=sys.stderr
            )
            return 1
        if not t["html"]["self_contained"]:
            print(f"INVARIANT VIOLATION: {t['name']} HTML made external requests", file=sys.stderr)
            return 1

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    print(f"Wrote {args.out}")
    for t in report["targets"]:
        print(
            f"  {t['name']}: {t['functions']} fns, {t['calls']} calls, "
            f"{t['ms']} ms, {t['functions_per_sec']} fns/s, "
            f"provenance {t['confidence']['provenance_pct']}%, "
            f"deterministic={t['determinism']['byte_identical']}, "
            f"self_contained_html={t['html']['self_contained']}"
        )
    if args.print:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
