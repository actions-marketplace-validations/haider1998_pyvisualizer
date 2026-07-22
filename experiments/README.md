# Experiments — does the context pack actually help?

`benchmarks/` answers *how fast* and *how deterministic*. This directory answers
the question the product claim actually rests on: **is the pack any good?**

The v2.2 claim for Job 2 ("verified context for AI agents") was backed by a single
number: *~96% fewer tokens than the full source*. That is a **size ratio, not a
quality measure** — a pack can be 96% smaller and 100% useless. Nothing measured
whether the pack contains the functions an agent actually needs.

So we measured it, against real GitHub issues with a known, human-reviewed fix.

> **Pre-registration.** Everything below — the arms, the metrics, the instance
> selection rule, and the drop rule — was written down *before* any result was
> read. The numbers live in `results/`; this document describes how they are
> produced, not what they turned out to be.

---

## The dataset

[SWE-bench Verified](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified):
500 human-validated GitHub issues across 12 Python projects. Each instance ships
its own ground truth:

| Field | What it is | Who may see it |
|---|---|---|
| `problem_statement` | the bug report | the agent, and the seeding logic |
| `patch` | the fix that was actually merged | **scoring only** |
| `test_patch` | the tests that prove it | **grading only, applied after the agent stops** |
| `FAIL_TO_PASS` | must flip fail → pass | grading |
| `PASS_TO_PASS` | must stay green (regression guard) | grading |

Fetched via the Hugging Face rows API (stdlib + `curl`, no `datasets` dependency)
and cached under `.cache/`.

---

## Track A — localization (the claim)

**No LLM, no Docker, no agent.** For each issue we check the repository out at the
commit *before* the fix, build the call graph, derive focus seeds from the issue
text, and ask each strategy — **under one shared token budget** — which functions
it would put in front of an agent. Then we score that selection against the
functions the merged fix actually touched.

> Because no model is in the loop, **training-data contamination cannot affect
> this track.** The usual objection to SWE-bench numbers does not apply.

### Arms (budget-matched: 4,000 tokens each, same estimator)

| Arm | What it is |
|---|---|
| `bm25` | Okapi BM25 over function source. The honest baseline — SWE-bench ships BM25 retrieval, and unlike the graph arms it gets to **read the actual code**. |
| `context_shipped` | py-code-visualizer v2.2 *exactly as released*, including the ranking bug described below. Present to quantify the damage, not to flatter. |
| `context_fixed` | The repaired selection: personalized PageRank over verified call edges. |
| `hybrid` | BM25 picks the entry points, the call graph expands them. Tests the real hypothesis: text finds *where to look*, the graph finds *what it touches*. |

### Leak-free seeding

`--focus` needs a starting symbol, but for an *unsolved* issue nobody has one. So
seeds are derived from the **bug report alone** — backticked spans, dotted paths,
and identifier-shaped words matched against graph symbols (`seeds.py`). That
module never receives `patch` or `test_patch`; the signature is the enforcement.
Instances where the issue text yields no seed at all are counted separately —
that number is itself a finding about the product.

### Metrics

Standard localization measures from the literature (Agentless, LocAgent):
file-level precision / recall / F1 / Jaccard, and function-level recall — plus
**recall per 1k tokens**, which is the efficiency claim stated honestly.

```bash
python -m experiments.localize --resume        # → results/localization.json
```

Instances are processed in a **pre-registered deterministic order** (sorted by
instance id), so stopping early yields an unbiased prefix, never a cherry-picked
sample.

---

## Track B — agent A/B pilot (illustration, not proof)

Two arms per issue, identical in every respect except one:

* **control** — the repository and the issue text.
* **pack** — the same, plus a `context` pack generated from that exact checkout.

Runs are executed by **cold Claude Code subagents**. A freshly spawned subagent
has no memory of the session that launched it, so it cannot know which arm it is
in or what the other arm did. (The headless `claude -p` path was unusable here —
it reports `Credit balance is too low`.)

**Grading is the real SWE-bench oracle**, not a proxy: install the project, apply
the held-out `test_patch`, run `FAIL_TO_PASS` (must flip) and `PASS_TO_PASS`
(must stay green). Dependency pins come from **SWE-bench's own published install
specs** (`envspec.py`) rather than from guesswork.

### Selection rule (fixed in advance)

1. Repos we can actually drive without Docker (`PILOT_REPOS`); sympy excluded
   because its bespoke runner would make harness failures look like agent
   failures.
2. Difficulty in `{<15 min fix, 15 min - 1 hour}`.
3. **Repo-stratified** round-robin sample, `seed=1998`. Plain random sampling
   returns all-django (231 of ~296 eligible), which would make the pilot a study
   of one codebase.

### Drop rule (applied before any agent runs)

`validate_envs.py` runs the oracle against an **untouched** checkout. A usable
instance must show `FAIL_TO_PASS` *failing* and `PASS_TO_PASS` *passing* — proof
the bug is really present and the suite is otherwise green. Anything else means
the environment is broken on this machine, not that an agent failed. Drops happen
before any agent runs and are recorded in `results/env_validation.json`.

### Honesty about power

n=8 cannot produce a statistically significant resolve-rate difference, and this
is not claimed. Track B is reported as a pilot with per-instance detail; **Track A
carries the statistical weight.**

### Contamination

Claude may have memorized SWE-bench fixes. This affects **both arms equally**, so
the paired difference remains meaningful, but the absolute resolve rate here
should not be read as a general capability measure.

---

## What this found first: a P0 bug in the feature being measured

Building the harness immediately exposed a shipped bug in `context`:

`nx.pagerank` dispatches to **SciPy**, which is *not* a dependency of this package
(`networkx` is). On a normal install the call raises `ModuleNotFoundError`, which
the code caught with a broad `except Exception` — the comment said "convergence
fallback", anticipating non-convergence rather than a missing library — and set
**every score to 0.0**. The tie-break `(-score, name)` then degraded to **plain
alphabetical order**.

Measured on `networkx` (7,159 functions), focusing on `pagerank`:

| | v2.2 as shipped | after the fix |
|---|---|---|
| Functions in pack | 51 | 60 |
| **With no connection at all to the focus** | **17 (33%)** | **0** |
| Ranking | alphabetical (`algorithms.approximation.clique.*` first) | personalized PageRank over call edges |

It also broke the project's own determinism invariant: identical input produced
different output depending on whether NumPy happened to be installed.

The fix replaces `nx.pagerank` with a dependency-free power iteration, walks call
edges **both ways** (a function's callers matter as much as its callees), and
refuses to spend budget on functions the focus cannot reach. Guarded by
`tests/test_review_context.py::TestPageRankIsSelfContained`.

---

## Reproducing

```bash
python -m experiments.dataset          # fetch + summarize the 500 instances
python -m experiments.localize --resume        # Track A
python -m experiments.validate_envs            # Track B pre-flight
python -m experiments.agent_ab select -n 8     # the pre-registered sample
python -m experiments.agent_ab prep  <id> <arm>
python -m experiments.agent_ab grade <id> <arm>
```

Requires network (clones the real repositories) and disk for the checkouts. Track
A takes roughly 20-25 s per instance, dominated by graph construction on large
repos like django and sympy.

## Limitations, stated up front

- **One interpreter.** SWE-bench pins a Python version per instance inside Docker;
  there is no Docker here, so every run uses the oldest interpreter available.
  Instances that won't build are dropped by the pre-flight, not silently.
- **Track B is a pilot** (n=8). Directional only.
- **Track A measures localization, not repair.** Finding the right function is
  necessary for a fix, not sufficient.
- **Seeding is deliberately simple.** A cleverer extractor might do better; it
  would also be an untested confound.
