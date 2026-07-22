"""Pre-flight: which pilot instances can this machine actually grade?

Runs the oracle against an *untouched* checkout of each selected instance. A
usable instance must show FAIL_TO_PASS **failing** (the bug is really there) and
PASS_TO_PASS **passing** (the suite is otherwise green). If either is wrong, the
environment is broken here — not the agent — and the instance is dropped.

This runs **before** any agent does anything, so dropping is blind to the result
we are trying to measure. Dropped instances and their reasons are recorded.

Because roughly half of the candidates fail to build on this machine (no Docker,
one interpreter, some suites need network), we walk a **larger candidate list in
the fixed seeded order** and keep the first ``--target`` that pass. The order is
decided in advance and validation cannot see the arms, so this selects on
"gradable here", never on "favourable to us".

Run:  python -m experiments.validate_envs --candidates 24 --target 8
"""

from __future__ import annotations

import argparse
import json
import os
import traceback
from typing import Any, Dict, List

from experiments.agent_ab import RESULTS_DIR, grade, prep, select_pilot

OUT = os.path.join(RESULTS_DIR, "env_validation.json")


def validate(n: int = 8, target: int = 0, resume: bool = False) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    done: set = set()
    if resume and os.path.exists(OUT):
        with open(OUT, "r", encoding="utf-8") as f:
            rows = json.load(f).get("validated", [])
        done = {r["instance_id"] for r in rows}

    for inst in select_pilot(n):
        if inst["instance_id"] in done:
            continue
        if target and sum(1 for r in rows if r.get("usable")) >= target:
            break
        iid = inst["instance_id"]
        row: Dict[str, Any] = {
            "instance_id": iid,
            "repo": inst["repo"],
            "version": inst.get("version", ""),
        }
        try:
            prep(iid, "control")
            g = grade(iid, "control")
            f2p_fails = not g["fail_to_pass"]["passed"]
            p2p_passes = g["pass_to_pass"]["passed"]
            row.update(
                {
                    "usable": bool(f2p_fails and p2p_passes and g["test_patch_applied"]),
                    "f2p_fails_before_fix": f2p_fails,
                    "p2p_passes_before_fix": p2p_passes,
                    "test_patch_applied": g["test_patch_applied"],
                    "install_mode": g["install_mode"],
                    "f2p_tail": g["fail_to_pass"]["output"][-400:],
                    "p2p_tail": g["pass_to_pass"]["output"][-400:],
                }
            )
        except Exception as e:
            row.update(
                {
                    "usable": False,
                    "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-600:],
                }
            )
        rows.append(row)
        status = "USABLE" if row.get("usable") else "DROP"
        print(
            f"  {status:7s} {iid:36s} {row.get('install_mode', row.get('error', ''))[:70]}",
            flush=True,
        )
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump({"validated": rows}, f, indent=2)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", type=int, default=8, help="How far down the seeded order to go")
    ap.add_argument(
        "--target", type=int, default=0, help="Stop once this many are usable (0 = all)"
    )
    ap.add_argument("--resume", action="store_true", help="Keep instances already validated")
    args = ap.parse_args()

    results = validate(args.candidates, args.target, args.resume)
    ok = [r for r in results if r.get("usable")]
    print(f"\n{len(ok)}/{len(results)} instances usable; written to {OUT}")
    for r in ok:
        print(f"  USABLE {r['instance_id']:36s} {r['repo']}")
