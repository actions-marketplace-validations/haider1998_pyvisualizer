# 🗺️ py-code-visualizer

[![PyPI](https://img.shields.io/pypi/v/py-code-visualizer.svg?color=7c3aed&label=py-code-visualizer)](https://pypi.org/project/py-code-visualizer/)
[![Downloads](https://img.shields.io/pypi/dm/py-code-visualizer.svg?color=2f81f7)](https://pypi.org/project/py-code-visualizer/)
[![CI](https://github.com/haider1998/PyVisualizer/actions/workflows/ci.yml/badge.svg)](https://github.com/haider1998/PyVisualizer/actions/workflows/ci.yml)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![architecture: verified](https://img.shields.io/badge/architecture-verified-3fb950.svg)](#architecture)

> **Deterministic, AST-verified architecture ground truth for Python.**
> LLMs guess your architecture. **py-code-visualizer proves it** — every edge is
> traceable to a `file:line`.

<p align="center">
  <img src="docs/images/terminal-demo.svg" alt="py-code-visualizer: pip install, then visualize your project into a self-contained interactive map" width="720">
</p>

<p align="center">
  <b><a href="https://haider1998.github.io/pyvisualizer/playground.html">⚡ Try it live in your browser →</a></b>
  &nbsp;·&nbsp; drop a <code>.py</code> file, see the graph, nothing uploaded
</p>

py-code-visualizer reads your Python source with static analysis (no code is ever
imported or executed) and produces a call graph you can trust: self-healing
README diagrams, PR architecture-change reports, CI gates that block circular
dependencies, and a fully offline interactive map. Because the output is
**deterministic**, it lives in your pipelines and never drifts.

```bash
pip install py-code-visualizer && py-code-visualizer visualize .
```

**Who is this for?** Any Python developer, whatever your stack:
[**Django**](https://haider1998.github.io/pyvisualizer/for/django.html) (real
request flow, not just the model schema) ·
[**FastAPI**](https://haider1998.github.io/pyvisualizer/for/fastapi.html) (every
route's blast radius, async + decorators) ·
[**ML pipelines**](https://haider1998.github.io/pyvisualizer/for/ml-pipelines.html)
(map the pipeline, find dead experiments). See the
[honest comparison](https://haider1998.github.io/pyvisualizer/compare.html) and
[measured facts](https://haider1998.github.io/pyvisualizer/facts.html).

---

## Why this exists (and why an LLM can't do it)

An LLM asked to diagram your repo produces the architecture it *expects* a repo
like yours to have — plausible, confident, and subtly wrong. It invents links
between modules that never call each other, silently drops what didn't fit the
context window, and gives a different answer every run, so you can never diff it
or put it in CI.

PyVisualizer is the opposite by construction:

| | LLM diagram | PyVisualizer |
|---|---|---|
| **Correctness** | Inferred, often hallucinated | Parsed from the AST |
| **Provenance** | None | Every edge → `file:line` |
| **Determinism** | Different every run | Byte-identical |
| **Ambiguity** | Hidden behind confidence | Flagged, with candidates kept |
| **CI-able** | No | Yes — gates, diffs, drift checks |
| **Code leaves the machine** | Usually | Never |

When a call genuinely can't be resolved to one target, we **don't pick one and
pretend** — we tag the edge `ambiguous` and keep the full candidate list. That
honesty is the whole product.

---

## Install

```bash
pip install py-code-visualizer
```

## 60-second start

```bash
# Interactive, fully self-contained HTML map (opens offline, zero network)
py-code-visualizer visualize ./your_project -o architecture.html

# Keep a live diagram inside your README forever
py-code-visualizer readme ./your_project

# Fail CI on new circular dependencies
py-code-visualizer check ./your_project --fail-on-cycles

# What breaks if I touch this function?
py-code-visualizer impact your_pkg.core.save ./your_project
```

---

## For a scrappy startup 🚀

You will never schedule a "docs sprint." So don't. Add one line to CI and your
README always carries a current architecture diagram — investor- and
due-diligence-ready for free — while every PR gets a comment showing exactly
what changed structurally.

```yaml
# .github/workflows/architecture.yml
- uses: haider1998/PyVisualizer@v2
  with: { mode: readme }
```

A new contractor onboards from the interactive map instead of a three-day Slack
Q&A. Pivots stop being archaeology.

## For a Fortune 500 enterprise 🏛️

- **Code never leaves the machine.** Pure AST, no execution, no API calls — the
  anti-LLM tool for security review. Generated HTML is a single file with zero
  network requests (air-gap safe).
- **Architecture-as-code gates.** Declare layers and forbidden dependencies;
  the build fails on violations — at the *call-graph* level, stricter than
  import linters.
- **Audit trail.** Deterministic diagrams committed by CI make git history your
  dated, attributable architecture change-log (SOC 2 / review boards).
- **Monorepo scale.** Hierarchical rollup (module → class → function), never
  silent sampling.

```toml
# pyproject.toml
[tool.pyvisualizer.rules]
layers = ["api", "domain", "infra"]
forbid = ["domain -> api", "domain -> infra"]
```

---

## Commands

| Command | What it does |
|---|---|
| `review <path> --base <ref>` | **PR review report**: changed functions, blast radius, risk flags, focused subgraph — clickable `file:line` on every reference |
| `context <path> --focus <fn>` | **Verified context pack for AI agents**: task-scoped, budget-bounded, zero guessed edges |
| `visualize` | Render `html` · `mermaid` · `json` · `c4` · `svg`/`png` |
| `readme` | Inject/update a Mermaid diagram in any Markdown file (idempotent) + jump-to-source index |
| `json` | Emit the canonical, diffable graph JSON |
| `diff base.json head.json` | PR-ready architecture-change report (+ new-cycle gate) |
| `check` | Enforce layering rules & cycles — CI gate (`--dead-code` too) |
| `impact <fn>` | Blast-radius: transitive callers/callees + risk line (`--format markdown`) |
| `health` | Architecture health score (A–F) with an SVG badge |
| `export` | `ARCHITECTURE.json` + `ARCHITECTURE.md` + AGENTS.md wiring (`--check` freshness gate) |
| `init` | Opt-in setup — generate only the automation you choose (`review`/`readme`/`context`/`gates`) |

**Two jobs, one engine.** *review* makes code review on a large repo a focused
few-minute pass; *context* gives an AI agent a verified, ~96%-smaller slice of the
architecture instead of the whole repo. See [`VISION.md`](VISION.md) and the
[use-case walkthroughs](https://haider1998.github.io/pyvisualizer/use-cases/).

## Use cases (real commands, real output)

Three end-to-end walkthroughs, each backed by a runnable fixture in
[`examples/scenarios/`](examples/scenarios) — every command and every line of
output is reproducible, nothing is staged:

- 🗺️ **[The orphan monolith](https://haider1998.github.io/pyvisualizer/use-cases/orphan-monolith.html)** —
  onboard onto an undocumented codebase with `visualize` + `health` + `check --dead-code`.
- 🛡️ **[The audit deadline](https://haider1998.github.io/pyvisualizer/use-cases/soc2-audit.html)** —
  enforce layering rules at the call-graph level and produce dated SOC 2 evidence.
- 🧨 **[The fearless refactor](https://haider1998.github.io/pyvisualizer/use-cases/fearless-refactor.html)** —
  `impact` blast radius, then a `diff` gate that fails a PR on a new cycle.

See the [full use-case index + a recipe for every command](https://haider1998.github.io/pyvisualizer/use-cases/).

**Measured** (reproduce with `python benchmarks/bench.py` → [`docs/benchmarks.json`](docs/benchmarks.json)):
a **98,669-line** project maps to a full call graph in **~4.9 s** (26,658 functions),
**100%** of edges carry `file:line`, output is **byte-identical** across runs, and the
generated HTML makes **0** network requests. *(macOS arm64, Python 3.14; speed is
hardware-dependent — provenance, determinism, and zero-network are structural.)*

## The interactive map

A single self-contained HTML file (no CDN, works offline):

- **Layered abstraction** — toggle module → class → function views
- **Click any node** — signature, `file:line`, callers & callees (all clickable)
- **⌘K command palette**, live search, module filter
- **Deep links** — the URL encodes the selected node; paste it in Slack and your
  teammate lands on the exact function
- **Tour mode** — auto-generated walkthrough from detected entry points
- **Overlays** — cycles (red), ambiguity (dashed), and `--churn` git-heatmap
- Minimap, pan/zoom/drag, light/dark, SVG export

## Feed the graph to your AI tools

```bash
py-code-visualizer export --for-ai ./your_project
```

Point Cursor / Claude at the verified `ARCHITECTURE.json` instead of asking a
model to re-derive structure from raw source. **Point your agent at the graph,
not the repo.**

---

## Accuracy guarantees

- Nested classes, methods, and closures are collected with correct qualified
  names (`pkg.Outer.Inner.method`, `mod.func.<locals>.inner`).
- Chained calls (`get_client().fetch()`), comprehensions, and lambdas are
  captured.
- `super()`/inherited calls resolved through the computed MRO (tagged
  `inherited`).
- Parameter and variable type annotations drive method resolution.
- Calls to stdlib/third-party code produce **no edge** — we never invent one.
- Ambiguous calls are tagged and kept as candidates; `--strict` drops them.

See [`docs/integrations.md`](docs/integrations.md) for GitHub Actions, GitLab
CI, and pre-commit setup.

## Configuration

```toml
[tool.pyvisualizer]
exclude = ["tests", "migrations"]
max_nodes = 120
target = "README.md"
detail = "module"          # module | class | function
```

## Roadmap

- ⏳ **Time-travel** — scrub your architecture's evolution across releases
- 🔁 **Watch mode** — live-reloading map while you refactor
- 🔌 **MCP server** — `who_calls`, `what_breaks_if_i_change` as agent tools

## Architecture

The diagram below is generated by PyVisualizer itself and kept in sync by CI.

<!-- pyvisualizer:start -->
<!-- This diagram is auto-generated by py-code-visualizer. Do not edit by hand; run `py-code-visualizer readme` to refresh. -->

*120 functions · 138 calls · health B+ (87/100) — detail: module*

```mermaid
flowchart LR
    g0["api"]
    g1["cli"]
    g2["config"]
    g3["analyzer"]
    g4["graph"]
    g5["model"]
    g6["resolver"]
    g7["diff"]
    g8["export"]
    g9["gates"]
    g10["impact"]
    g11["inject"]
    g12["metrics"]
    g13["overlays"]
    g14["c4"]
    g15["json_graph"]
    g16["file_discovery"]
    g17["d3"]
    g18["html"]
    g19["mermaid"]
    g0 --> g4
    g0 --> g6
    g0 --> g16
    g1 --> g0
    g1 --> g2
    g1 --> g7
    g1 --> g8
    g1 --> g9
    g1 --> g10
    g1 --> g11
    g1 --> g12
    g1 --> g13
    g1 --> g14
    g1 --> g15
    g1 --> g17
    g1 --> g19
    g7 --> g12
    g8 -.-> g5
    g8 --> g9
    g8 --> g12
    g8 --> g15
    g14 --> g19
    g17 --> g18
    g18 --> g15
```

<sub>🔒 Deterministic, AST-verified — no code executed. Generated by [py-code-visualizer](https://github.com/haider1998/PyVisualizer).</sub>
<!-- pyvisualizer:end -->

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PyVisualizer is MIT-licensed.
