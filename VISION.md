# Vision — py-code-visualizer

*The north star. Every feature must trace back to something on this page. If a
proposed change doesn't serve one of the two jobs below, it doesn't ship.*

## The problem

Two things are true about working in a large Python codebase:

1. **Humans can't review what they can't see.** On a big repo, no reviewer has
   time to read every file. Faced with a diff, they need to know — fast — *what
   functions actually changed, what those changes can reach, and where to look*.
   Without that, review is either shallow (rubber-stamp) or slow (spelunking).

2. **AI agents can't be accurate about structure they guess.** LLMs re-derive a
   project's architecture from raw source on every task. They hallucinate call
   relationships, miss what didn't fit the context window, and burn tokens
   re-reading files to reconstruct facts that could simply be *looked up*.

Both problems have the same root: **the call graph is real, knowable, and
verifiable — but nobody has it in front of them at the moment they need it.**

## The two jobs

Everything this tool does serves exactly one of these:

- **Job 1 — Focused code review.** Turn a diff into "here is what changed, here
  is the blast radius, here are the exact call sites to look at," with a link
  into every one. Make a large-repo review a 5-minute focused pass instead of a
  3-hour crawl.

- **Job 2 — Verified agent context.** Hand an AI agent a compact, task-scoped,
  100%-verified slice of the architecture — fewer tokens, higher accuracy than
  it could ever derive itself — and make sure it actually uses it.

The unifying engine is one idea: **change → impacted subgraph → focused
artifact.** Rendered for a human, that artifact is a review report. Rendered for
a machine, it's a context pack. Same graph, same provenance, two audiences.

## Principles (in priority order)

1. **Accuracy is the moat.** An LLM cannot match a parsed AST. We never
   fabricate an edge; a call we can't resolve to one target is flagged
   `ambiguous` with candidates kept, never guessed. If we ever trade accuracy
   for a feature, we've lost the only thing that makes us worth using.
2. **Provenance on every claim.** Every node and edge carries `file:line`. A
   claim you can't click into is a claim you can't trust.
3. **Deterministic output.** Two runs on unchanged code produce byte-identical
   results. This is what lets our output live in CI, README, and PR gates.
4. **Simple surface, earned complexity.** The user-facing experience is crisp
   and minimal; complexity lives underneath and only when it pays for itself.
   We never overwhelm a user with everything when they came for one thing.
5. **Additive evolution.** Existing capabilities are never demised or broken.
   New problems (especially AI-era ones) get new *additions*, never regressions.
6. **Measured claims only.** Every number we publish comes from a re-runnable
   benchmark. No invented metrics; no unmeasurable "X% more accurate."

## Feature map (each tagged with the job it serves)

| Command | Job | What it gives |
|---|---|---|
| `visualize` | 1 | Interactive map / Mermaid / JSON / C4 / SVG-PNG |
| `review` | 1 | PR review report: changed fns, blast radius, risk flags, focused subgraph |
| `impact` | 1 | Blast radius of one function |
| `diff` | 1 | Architecture delta between two snapshots + new-cycle gate |
| `check` | 1 | Layer/cycle gates for CI |
| `health` | 1 | A–F architecture grade |
| `readme` | 1 | Self-healing diagram in Markdown |
| `context` | 2 | Task-scoped, budget-bounded, verified context pack for agents |
| `export` | 2 | ARCHITECTURE.json/md + AGENTS.md wiring so agents consume ground truth |
| `json` | 1+2 | The canonical graph both humans and machines build on |
| `init` | — | Opt-in onboarding: pick only the automation you want |

## The decision filter for any new idea

Before building anything, answer three questions:

1. **Which job does it serve — review, or agent context?** If neither, stop.
2. **Can its accuracy be proven?** If it would require guessing, it must flag
   the uncertainty instead. No exceptions.
3. **Is there a simpler way to deliver the same value?** Prefer the boring,
   dependency-free version. Reach for complexity only when the simple version
   genuinely can't do the job.

If a good idea can't answer these cleanly, it goes on the "later, deliberately"
list rather than into the product.

## Later, deliberately (roadmap — not built yet, on purpose)

- **MCP server** (`who_calls`, `what_breaks_if_i_change` as live agent tools) —
  the always-on successor to the AGENTS.md convention. Deferred until the
  convention proves the demand; a server is complexity we add only when earned.
- **Incremental AST caching** for very large monorepos — determinism-safe,
  keyed on file content hash. Only when real repos hit a real speed wall.
- **Coverage overlay** (`--coverage coverage.xml`) joining churn on the existing
  overlay mechanism — the "untested × high-blast-radius" list.

## Explicitly not building

- **Time-travel history** and **live watch mode** — interesting, but neither
  serves the two jobs enough to justify the surface area.
- **Anything that guesses** to look more complete. A confident wrong answer is
  the LLM failure mode we exist to replace, not imitate.
