"""Read the Track A results and report the comparison honestly.

Arms are evaluated on the *same* instances, so the right test is a **paired**
one. We use the Wilcoxon signed-rank test (no normality assumption) and report an
effect size alongside it, because with 500 instances a trivial difference can be
"significant" and mean nothing in practice.

Implemented without SciPy, in keeping with the rest of the project: the normal
approximation to the signed-rank statistic is used, with a tie correction.

Run:  python -m experiments.analyze
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import Any, Dict, List, Sequence, Tuple

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "localization.json")


def _median(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def _rank_with_ties(values: Sequence[float]) -> List[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def wilcoxon(a: Sequence[float], b: Sequence[float]) -> Dict[str, Any]:
    """Paired Wilcoxon signed-rank, normal approximation with tie correction."""
    diffs = [x - y for x, y in zip(a, b) if x != y]
    n = len(diffs)
    if n < 6:  # too few non-zero differences for the approximation to mean much
        return {"n_nonzero": n, "p_value": None, "note": "too few differences for a normal approx"}
    ranks = _rank_with_ties([abs(d) for d in diffs])
    w_plus = sum(r for d, r in zip(diffs, ranks) if d > 0)
    mean = n * (n + 1) / 4.0
    # Tie correction on the variance.
    counts: Dict[float, int] = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    tie_term = sum(t**3 - t for t in counts.values())
    var = (n * (n + 1) * (2 * n + 1) - tie_term / 2.0) / 24.0
    if var <= 0:
        return {"n_nonzero": n, "p_value": None, "note": "zero variance"}
    z = (w_plus - mean) / math.sqrt(var)
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))
    return {
        "n_nonzero": n,
        "z": round(z, 3),
        "p_value": p,
        "wins_a": sum(1 for d in diffs if d > 0),
    }


def bootstrap_ci(
    values: Sequence[float], iters: int = 2000, seed: int = 1998
) -> Tuple[float, float]:
    """Percentile bootstrap CI for the mean. Seeded, so the number is stable."""
    import random

    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(iters):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return (round(means[int(0.025 * iters)], 4), round(means[int(0.975 * iters)], 4))


def analyze(path: str = RESULTS) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    records = data["records"]
    arms: List[str] = data["arms"]

    usable = [r for r in records if r["gold_files"]]
    with_funcs = [r for r in usable if r["gold_functions_resolved"]]

    report: Dict[str, Any] = {
        "instances_total": len(records),
        "instances_scored": len(usable),
        "instances_with_resolved_gold_functions": len(with_funcs),
        "instances_with_zero_seeds": sum(1 for r in usable if r["seed_count"] == 0),
        "failures": len(data.get("failures", [])),
        "arms": {},
        "paired_vs_bm25": {},
    }

    for arm in arms:
        fr = [r["arms"][arm]["file_recall"] for r in usable]
        fn = [r["arms"][arm]["func_recall"] for r in with_funcs]
        eff = [r["arms"][arm]["func_recall_per_1k"] for r in with_funcs]
        tok = [float(r["arms"][arm]["tokens"]) for r in usable]
        report["arms"][arm] = {
            "file_recall_mean": round(sum(fr) / len(fr), 4) if fr else 0.0,
            "file_recall_ci95": bootstrap_ci(fr),
            "func_recall_mean": round(sum(fn) / len(fn), 4) if fn else 0.0,
            "func_recall_ci95": bootstrap_ci(fn),
            "any_gold_file_found_pct": (
                round(
                    100.0
                    * sum(1 for r in usable if r["arms"][arm]["any_gold_file_found"])
                    / len(usable),
                    1,
                )
                if usable
                else 0.0
            ),
            "any_gold_func_found_pct": (
                round(
                    100.0
                    * sum(1 for r in with_funcs if r["arms"][arm]["any_gold_func_found"])
                    / len(with_funcs),
                    1,
                )
                if with_funcs
                else 0.0
            ),
            "func_recall_per_1k_median": round(_median(eff), 4),
            "tokens_median": round(_median(tok), 1),
        }

    # Everything is compared against the retrieval baseline, not against the
    # broken version of ourselves — beating our own bug proves nothing.
    if "bm25" in arms:
        base_fn = [r["arms"]["bm25"]["func_recall"] for r in with_funcs]
        base_eff = [r["arms"]["bm25"]["func_recall_per_1k"] for r in with_funcs]
        for arm in arms:
            if arm == "bm25":
                continue
            fn = [r["arms"][arm]["func_recall"] for r in with_funcs]
            eff = [r["arms"][arm]["func_recall_per_1k"] for r in with_funcs]
            report["paired_vs_bm25"][arm] = {
                "func_recall": wilcoxon(fn, base_fn),
                "func_recall_per_1k": wilcoxon(eff, base_eff),
                "mean_delta_func_recall": round(
                    (sum(fn) / len(fn) - sum(base_fn) / len(base_fn)) if fn else 0.0, 4
                ),
            }
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default=RESULTS)
    args = ap.parse_args()
    rep = analyze(args.results)

    print(
        f"Instances scored: {rep['instances_scored']} "
        f"(gold functions resolved on {rep['instances_with_resolved_gold_functions']}; "
        f"{rep['instances_with_zero_seeds']} had no usable seed; {rep['failures']} failed)"
    )
    print()
    hdr = f"{'arm':18s} {'file_recall':>12s} {'func_recall':>12s} {'found_any_fn%':>14s} {'tokens':>8s} {'recall/1k':>10s}"
    print(hdr)
    print("-" * len(hdr))
    for arm, m in rep["arms"].items():
        print(
            f"{arm:18s} {m['file_recall_mean']:12.3f} {m['func_recall_mean']:12.3f} "
            f"{m['any_gold_func_found_pct']:13.1f}% {m['tokens_median']:8.0f} "
            f"{m['func_recall_per_1k_median']:10.3f}"
        )
    print("\nPaired vs bm25 (Wilcoxon signed-rank):")
    for arm, m in rep["paired_vs_bm25"].items():
        w = m["func_recall"]
        p = w.get("p_value")
        p_str = f"p={p:.2e}" if isinstance(p, float) else f"({w.get('note', 'n/a')})"
        print(
            f"  {arm:18s} Δmean_func_recall={m['mean_delta_func_recall']:+.4f}  {p_str}  n={w['n_nonzero']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
