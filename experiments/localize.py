"""Track A — the localization benchmark. No LLM, no Docker, no agent.

For each real GitHub issue: check the repo out at the commit *before* the fix,
build the call graph, derive focus seeds from the issue text alone, then ask every
arm for its selection under one shared token budget and score it against the
functions the merged fix actually touched.

Because no model is in the loop, this track is immune to training-data
contamination — the usual objection to SWE-bench results does not apply here.

Instances are processed in a **pre-registered deterministic order** (sorted by
instance id), so stopping early yields an unbiased prefix rather than a
cherry-picked sample.

Run:  python -m experiments.localize --limit 50
"""

from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from typing import Any, Dict, List

from experiments import dataset, gold, repos, seeds
from experiments.retrieval import ARMS, build_bm25, run_arm, score
from pyvisualizer.api import build_graph
from pyvisualizer.overlays import _toplevel

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
DEFAULT_OUT = os.path.join(RESULTS_DIR, "localization.json")


def _rel_paths(root: str, files: Any) -> set:
    return {f.replace(os.sep, "/") for f in files}


def run_instance(
    inst: Dict[str, Any],
    budget_tokens: int,
    arms: List[str],
) -> Dict[str, Any]:
    """Evaluate every arm on one issue. Raises only on unexpected failures."""
    t0 = time.perf_counter()
    repo = inst["repo"]
    checkout_path = repos.checkout(repo, inst["base_commit"])
    src_root = repos.source_root(repo, checkout_path)

    result = build_graph(src_root)
    G = result.graph
    top = _toplevel(result.project_root) or os.path.abspath(result.project_root)

    truth = gold.parse_patch(inst["patch"])
    truth = gold.resolve_functions(truth, G, src_root)
    gold_files = _rel_paths(checkout_path, truth.files)
    gold_functions = set(truth.functions)

    # Seeds come from the issue text ONLY — never the patch.
    seed_nodes = seeds.derive_seeds(inst["problem_statement"], G)

    bm25 = build_bm25(G)
    per_arm: Dict[str, Any] = {}
    for arm in arms:
        selected = run_arm(
            arm,
            result,
            seed_nodes,
            inst["problem_statement"],
            budget_tokens,
            bm25=bm25,
        )
        per_arm[arm] = score(G, selected, gold_files, gold_functions, top, checkout_path)

    return {
        "instance_id": inst["instance_id"],
        "repo": repo,
        "difficulty": inst.get("difficulty", ""),
        "graph_functions": G.number_of_nodes(),
        "graph_calls": G.number_of_edges(),
        "gold_files": sorted(gold_files),
        "gold_functions": sorted(gold_functions),
        "gold_functions_resolved": bool(gold_functions),
        "seeds": seed_nodes,
        "seed_count": len(seed_nodes),
        "arms": per_arm,
        "seconds": round(time.perf_counter() - t0, 2),
    }


def aggregate(records: List[Dict[str, Any]], arms: List[str]) -> Dict[str, Any]:
    """Mean/median per arm. Function metrics only over instances where the gold
    functions actually resolved to graph nodes — otherwise the denominator is a
    parsing failure of ours, not a miss by the arm."""

    def _median(xs: List[float]) -> float:
        if not xs:
            return 0.0
        s = sorted(xs)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0

    usable = [r for r in records if r["gold_files"]]
    with_funcs = [r for r in usable if r["gold_functions_resolved"]]
    out: Dict[str, Any] = {
        "instances_scored": len(usable),
        "instances_with_resolved_gold_functions": len(with_funcs),
        "instances_with_zero_seeds": sum(1 for r in usable if r["seed_count"] == 0),
        "arms": {},
    }
    for arm in arms:
        file_metrics = [r["arms"][arm] for r in usable]
        func_metrics = [r["arms"][arm] for r in with_funcs]
        out["arms"][arm] = {
            "file_recall_mean": (
                round(sum(m["file_recall"] for m in file_metrics) / len(file_metrics), 4)
                if file_metrics
                else 0.0
            ),
            "file_f1_mean": (
                round(sum(m["file_f1"] for m in file_metrics) / len(file_metrics), 4)
                if file_metrics
                else 0.0
            ),
            "any_gold_file_found_pct": (
                round(
                    100.0 * sum(m["any_gold_file_found"] for m in file_metrics) / len(file_metrics),
                    1,
                )
                if file_metrics
                else 0.0
            ),
            "func_recall_mean": (
                round(sum(m["func_recall"] for m in func_metrics) / len(func_metrics), 4)
                if func_metrics
                else 0.0
            ),
            "any_gold_func_found_pct": (
                round(
                    100.0 * sum(m["any_gold_func_found"] for m in func_metrics) / len(func_metrics),
                    1,
                )
                if func_metrics
                else 0.0
            ),
            "func_recall_per_1k_median": round(
                _median([m["func_recall_per_1k"] for m in func_metrics]), 4
            ),
            "tokens_median": _median([float(m["tokens"]) for m in file_metrics]),
            "selected_median": _median([float(m["selected"]) for m in file_metrics]),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="Max instances (0 = all)")
    ap.add_argument("--budget-tokens", type=int, default=4000)
    ap.add_argument("--repos", default="", help="Comma-separated repo filter")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--resume", action="store_true", help="Skip instances already in --out")
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    data = dataset.load()
    if args.repos:
        wanted = {r.strip() for r in args.repos.split(",")}
        data = [d for d in data if d["repo"] in wanted]
    # Pre-registered deterministic order.
    data.sort(key=lambda d: d["instance_id"])
    if args.limit:
        data = data[: args.limit]

    records: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    done: set = set()
    if args.resume and os.path.exists(args.out):
        with open(args.out, "r", encoding="utf-8") as f:
            prev = json.load(f)
        records = prev.get("records", [])
        failures = prev.get("failures", [])
        done = {r["instance_id"] for r in records} | {f["instance_id"] for f in failures}

    os.makedirs(RESULTS_DIR, exist_ok=True)
    for i, inst in enumerate(data, 1):
        if inst["instance_id"] in done:
            continue
        try:
            rec = run_instance(inst, args.budget_tokens, arms)
            records.append(rec)
            best = max(arms, key=lambda a: rec["arms"][a]["func_recall"])
            print(
                f"[{i}/{len(data)}] {rec['instance_id']:38s} "
                f"fns={rec['graph_functions']:5d} seeds={rec['seed_count']:2d} "
                f"gold_fn={len(rec['gold_functions'])} best={best} "
                f"({rec['seconds']}s)",
                flush=True,
            )
        except Exception as e:  # keep going; failures are logged, never hidden
            failures.append(
                {
                    "instance_id": inst["instance_id"],
                    "repo": inst["repo"],
                    "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-800:],
                }
            )
            print(f"[{i}/{len(data)}] FAILED {inst['instance_id']}: {e}", flush=True)

        if i % 5 == 0 or i == len(data):
            _write(args, arms, records, failures)

    _write(args, arms, records, failures)
    summary = aggregate(records, arms)
    print("\n=== Aggregate ===")
    print(json.dumps(summary, indent=2))
    return 0


def _write(
    args: argparse.Namespace,
    arms: List[str],
    records: List[Dict[str, Any]],
    failures: List[Dict[str, str]],
) -> None:
    payload = {
        "generated_with": "experiments/localize.py",
        "note": "Reproduce: python -m experiments.localize",
        "dataset": dataset.DATASET,
        "budget_tokens": args.budget_tokens,
        "arms": arms,
        "aggregate": aggregate(records, arms),
        "records": records,
        "failures": failures,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
