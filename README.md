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

## ⚡ AI agent context — 97% fewer tokens

> **Full guide:** [AI_CONTEXT.md](AI_CONTEXT.md)

Instead of pasting your whole codebase into Claude / ChatGPT / Cursor, give it the
verified 4,000-token slice that actually matters. Three commands cover every workflow:

```bash
# Option A — describe the task in plain English (no function name needed)
py-code-visualizer context . --task "add retry logic to the HTTP client" --budget-tokens 4000

# Option B — you know the function
py-code-visualizer context . --focus send_request --budget-tokens 4000

# Option C — wire it in permanently (agents read it automatically)
py-code-visualizer export --for-ai .
```

**Copy the output of A or B → paste it before your question in the AI chat.**
The AI now has the right context instead of 140,000 guessed tokens.

| Approach | Tokens | Claude Opus 5 cost | Signal per 1k tokens |
|---|---|---|---|
| Full source | 139,697 | $2.10 | 1× |
| Keyword grep | 24,652 | $0.37 | 6× |
| **pyvisualizer `--task`** | **~4,000** | **$0.06** | **35×** |

_Measured on httpx (real open-source project, 1,076 functions). See [measured facts](https://haider1998.github.io/pyvisualizer/use-cases/agent-context.html)._

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
| `context <path> --task "<prose>"` | Same pack, seeded from a **natural-language task description** (named symbols first, lexical matches as labeled hints; `--strategy graph\|text\|hybrid`) |
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
few-minute pass; *context* gives an AI agent a verified, **97%-smaller** slice of the
architecture instead of the whole repo. See [`VISION.md`](VISION.md) and the
[use-case walkthroughs](https://haider1998.github.io/pyvisualizer/use-cases/).

### MCP server (real-time, mid-task)

If you use Claude Code or Cursor, the MCP server lets the agent query the verified
graph when it needs it — no manual copy-paste required:

```bash
pip install 'py-code-visualizer[mcp]'   # Python 3.10+
pyvisualizer-mcp /path/to/project
```

Add to `.mcp.json` and three tools become available: `search_code`, `context_pack`,
and `impact`. The server rebuilds only when files change.

Full usage guide (all flags, troubleshooting, output walkthrough): **[AI_CONTEXT.md](AI_CONTEXT.md)**

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
- ✅ ~~**MCP server**~~ — shipped: `pyvisualizer-mcp` (`search_code`, `context_pack`, `impact`)

## Architecture

The diagram below is generated by PyVisualizer itself and kept in sync by CI.

<!-- pyvisualizer:start -->
<!-- This diagram is auto-generated by py-code-visualizer. Do not edit by hand; run `py-code-visualizer readme` to refresh. -->

*120 functions · 213 calls · health F (46/100) — detail: module*

```mermaid
flowchart LR
    g0["bench"]
    g1["genproject"]
    g2["main"]
    g3["models"]
    g4["services"]
    g5["urls"]
    g6["repos"]
    g7["services"]
    g8["evaluate"]
    g9["features"]
    g10["ingest"]
    g11["pipeline"]
    g12["train"]
    g13["cli"]
    g14["pipeline"]
    g15["transforms"]
    g16["core"]
    g17["service"]
    g18["billing"]
    g19["api"]
    g20["changes"]
    g21["cli"]
    g22["config"]
    g23["context"]
    g24["analyzer"]
    g25["graph"]
    g26["diff"]
    g27["export"]
    g28["gates"]
    g29["impact"]
    g30["inject"]
    g31["mcp_server"]
    g32["metrics"]
    g33["overlays"]
    g34["retrieval"]
    g35["review"]
    g36["c4"]
    g37["json_graph"]
    g38["setup_init"]
    g39["file_discovery"]
    g40["d3"]
    g41["html"]
    g42["mermaid"]
    g0 --> g1
    g0 --> g19
    g0 --> g37
    g0 --> g41
    g1 --> g6
    g4 --> g3
    g7 -.-> g4
    g7 --> g6
    g11 --> g8
    g11 --> g9
    g11 --> g10
    g11 --> g12
    g13 --> g14
    g14 -.-> g7
    g14 --> g15
    g15 -.-> g4
    g17 --> g16
    g19 --> g25
    g19 --> g31
    g19 --> g39
    g20 --> g31
    g20 --> g33
    g21 --> g14
    g21 --> g19
    g21 --> g22
    g21 --> g23
    g21 --> g26
    g21 --> g27
    g21 --> g28
    g21 --> g29
    g21 --> g30
    g21 --> g31
    g21 --> g32
    g21 --> g33
    g21 --> g35
    g21 --> g36
    g21 --> g37
    g21 --> g40
    g21 --> g42
    g22 --> g31
    g23 --> g4
    g23 --> g20
    g23 --> g28
    g23 --> g29
    g23 --> g31
    g23 --> g32
    g23 --> g33
    g23 --> g34
    g24 --> g31
    g25 --> g4
    g25 --> g31
    g26 --> g4
    g26 --> g31
    g26 --> g32
    g27 --> g28
    g27 --> g30
    g27 --> g31
    g27 --> g32
    g27 --> g37
    g28 --> g31
    g29 --> g20
    g31 --> g19
    g31 --> g23
    g31 --> g29
    g31 --> g34
    g32 --> g31
    g32 --> g34
    g33 --> g31
    g34 --> g4
    g34 --> g31
    g35 --> g20
    g35 --> g28
    g35 --> g31
    g35 --> g32
    g35 --> g42
    g36 --> g42
    g37 --> g31
    g38 --> g19
    g38 --> g30
    g38 --> g31
    g38 --> g32
    g38 --> g42
    g39 --> g4
    g39 --> g6
    g40 --> g41
    g41 --> g37
    g42 --> g31
```

<sub>🔒 Deterministic, AST-verified — no code executed. Generated by [py-code-visualizer](https://github.com/haider1998/PyVisualizer).</sub>

<details>
<summary>📍 Jump to source (120 functions)</summary>

- [`benchmarks.bench._bench_target`](benchmarks/bench.py#L177)
- [`benchmarks.bench._determinism_proof`](benchmarks/bench.py#L113)
- [`benchmarks.bench._html_network_proof`](benchmarks/bench.py#L132)
- [`benchmarks.bench.run`](benchmarks/bench.py#L221)
- [`benchmarks.genproject._gen_module`](benchmarks/genproject.py#L41)
- [`benchmarks.genproject.generate`](benchmarks/genproject.py#L135)
- [`examples.sample_project.main.main`](examples/sample_project/main.py#L7)
- [`examples.scenarios.django_shop.models.Cart.for_user`](examples/scenarios/django_shop/models.py#L12)
- [`examples.scenarios.django_shop.services.CartService.add`](examples/scenarios/django_shop/services.py#L11)
- [`examples.scenarios.django_shop.services.OrderService.checkout`](examples/scenarios/django_shop/services.py#L22)
- [`examples.scenarios.django_shop.services.OrderService.get`](examples/scenarios/django_shop/services.py#L29)
- [`examples.scenarios.django_shop.urls.dispatch`](examples/scenarios/django_shop/urls.py#L7)
- [`examples.scenarios.fastapi_svc.repos.OrderRepo.insert`](examples/scenarios/fastapi_svc/repos.py#L8)
- [`examples.scenarios.fastapi_svc.services.OrderFlow.fetch`](examples/scenarios/fastapi_svc/services.py#L22)
- [`examples.scenarios.fastapi_svc.services.OrderFlow.place`](examples/scenarios/fastapi_svc/services.py#L16)
- [`examples.scenarios.ml_pipeline.evaluate.evaluate_model`](examples/scenarios/ml_pipeline/evaluate.py#L4)
- [`examples.scenarios.ml_pipeline.features.build_features`](examples/scenarios/ml_pipeline/features.py#L4)
- [`examples.scenarios.ml_pipeline.ingest.load_dataset`](examples/scenarios/ml_pipeline/ingest.py#L4)
- [`examples.scenarios.ml_pipeline.pipeline.run`](examples/scenarios/ml_pipeline/pipeline.py#L9)
- [`examples.scenarios.ml_pipeline.train.train_model`](examples/scenarios/ml_pipeline/train.py#L4)
- [`examples.scenarios.orphan_monolith.app.cli.run`](examples/scenarios/orphan_monolith/app/cli.py#L7)
- [`examples.scenarios.orphan_monolith.app.pipeline.ReportPipeline.build`](examples/scenarios/orphan_monolith/app/pipeline.py#L11)
- [`examples.scenarios.orphan_monolith.app.pipeline.ReportPipeline.render`](examples/scenarios/orphan_monolith/app/pipeline.py#L16)
- [`examples.scenarios.orphan_monolith.app.transforms.summarize`](examples/scenarios/orphan_monolith/app/transforms.py#L11)
- [`examples.scenarios.refactor.after.core.persist`](examples/scenarios/refactor/after/core.py#L7)
- [`examples.scenarios.refactor.after.service.cancel_order`](examples/scenarios/refactor/after/service.py#L11)
- [`examples.scenarios.refactor.after.service.place_order`](examples/scenarios/refactor/after/service.py#L7)
- [`examples.scenarios.soc2_audit.domain.billing.BillingService.charge`](examples/scenarios/soc2_audit/domain/billing.py#L12)
- [`pyvisualizer.api.build_graph`](pyvisualizer/api.py#L47)
- [`pyvisualizer.changes.Linker.ref`](pyvisualizer/changes.py#L202)
- [`pyvisualizer.changes.changed_lines_from_git`](pyvisualizer/changes.py#L62)
- [`pyvisualizer.changes.map_lines_to_functions`](pyvisualizer/changes.py#L121)
- [`pyvisualizer.changes.repo_web_url`](pyvisualizer/changes.py#L149)
- [`pyvisualizer.changes.resolve_base_ref`](pyvisualizer/changes.py#L46)
- [`pyvisualizer.cli._build`](pyvisualizer/cli.py#L283)
- [`pyvisualizer.cli._render_graphviz`](pyvisualizer/cli.py#L368)
- [`pyvisualizer.cli.cmd_check`](pyvisualizer/cli.py#L588)
- [`pyvisualizer.cli.cmd_context`](pyvisualizer/cli.py#L706)
- [`pyvisualizer.cli.cmd_diff`](pyvisualizer/cli.py#L550)
- [`pyvisualizer.cli.cmd_export`](pyvisualizer/cli.py#L647)
- [`pyvisualizer.cli.cmd_health`](pyvisualizer/cli.py#L623)
- [`pyvisualizer.cli.cmd_impact`](pyvisualizer/cli.py#L669)
- [`pyvisualizer.cli.cmd_readme`](pyvisualizer/cli.py#L458)
- [`pyvisualizer.cli.cmd_review`](pyvisualizer/cli.py#L681)
- [`pyvisualizer.cli.cmd_visualize`](pyvisualizer/cli.py#L302)
- [`pyvisualizer.cli.main`](pyvisualizer/cli.py#L264)
- [`pyvisualizer.config.load_config`](pyvisualizer/config.py#L102)
- [`pyvisualizer.context._est_tokens`](pyvisualizer/context.py#L134)
- [`pyvisualizer.context._node_line`](pyvisualizer/context.py#L109)
- [`pyvisualizer.context._resolve_focus`](pyvisualizer/context.py#L82)
- [`pyvisualizer.context._select_nodes`](pyvisualizer/context.py#L245)
- [`pyvisualizer.context._select_text`](pyvisualizer/context.py#L288)
- [`pyvisualizer.context._upgrade_bodies`](pyvisualizer/context.py#L317)
- [`pyvisualizer.context.build_context_pack`](pyvisualizer/context.py#L366)
- [`pyvisualizer.core.analyzer.DefinitionCollector._visit_function`](pyvisualizer/core/analyzer.py#L360)
- [`pyvisualizer.core.analyzer.DefinitionCollector.visit_ClassDef`](pyvisualizer/core/analyzer.py#L327)
- [`pyvisualizer.core.analyzer.ModuleAnalyzer._decorator_names`](pyvisualizer/core/analyzer.py#L158)
- [`pyvisualizer.core.analyzer.ModuleAnalyzer._extract_attribute_chain`](pyvisualizer/core/analyzer.py#L189)
- [`pyvisualizer.core.analyzer.ModuleAnalyzer._process_annotation`](pyvisualizer/core/analyzer.py#L259)
- [`pyvisualizer.core.analyzer.ModuleAnalyzer._process_decorator`](pyvisualizer/core/analyzer.py#L206)
- [`pyvisualizer.core.graph.FunctionCallVisitor._extract_attribute_chain`](pyvisualizer/core/graph.py#L421)
- [`pyvisualizer.core.graph.FunctionCallVisitor._extract_call_target`](pyvisualizer/core/graph.py#L407)
- [`pyvisualizer.core.graph.FunctionCallVisitor._find_method_in_hierarchy`](pyvisualizer/core/graph.py#L329)
- [`pyvisualizer.core.graph.FunctionCallVisitor._resolve_call`](pyvisualizer/core/graph.py#L201)
- [`pyvisualizer.core.graph.FunctionCallVisitor._seed_param_types`](pyvisualizer/core/graph.py#L121)
- [`pyvisualizer.core.graph.FunctionCallVisitor._visit_function_common`](pyvisualizer/core/graph.py#L96)
- [`pyvisualizer.core.graph.build_call_graph`](pyvisualizer/core/graph.py#L475)
- [`pyvisualizer.diff.diff_graphs`](pyvisualizer/diff.py#L84)
- [`pyvisualizer.diff.render_change_mermaid`](pyvisualizer/diff.py#L131)
- [`pyvisualizer.diff.render_markdown`](pyvisualizer/diff.py#L170)
- [`pyvisualizer.export._agents_md_plan`](pyvisualizer/export.py#L154)
- [`pyvisualizer.export._json_content`](pyvisualizer/export.py#L113)
- [`pyvisualizer.export.build_ai_markdown`](pyvisualizer/export.py#L32)
- [`pyvisualizer.export.export_for_ai`](pyvisualizer/export.py#L173)
- [`pyvisualizer.export.export_would_change`](pyvisualizer/export.py#L199)
- [`pyvisualizer.gates.check_layer_rules`](pyvisualizer/gates.py#L53)
- [`pyvisualizer.gates.find_cycles`](pyvisualizer/gates.py#L83)
- [`pyvisualizer.impact.analyze_impact`](pyvisualizer/impact.py#L46)
- [`pyvisualizer.impact.render_markdown`](pyvisualizer/impact.py#L96)
- [`pyvisualizer.impact.resolve_target`](pyvisualizer/impact.py#L32)
- [`pyvisualizer.inject.inject`](pyvisualizer/inject.py#L84)
- [`pyvisualizer.inject.inject_block`](pyvisualizer/inject.py#L51)
- [`pyvisualizer.inject.update_file`](pyvisualizer/inject.py#L102)
- [`pyvisualizer.mcp_server.ProjectSession.get`](pyvisualizer/mcp_server.py#L54)
- [`pyvisualizer.mcp_server.tool_context_pack`](pyvisualizer/mcp_server.py#L82)
- [`pyvisualizer.mcp_server.tool_impact`](pyvisualizer/mcp_server.py#L107)
- [`pyvisualizer.metrics._is_entry_point`](pyvisualizer/metrics.py#L75)
- [`pyvisualizer.metrics.compute_health`](pyvisualizer/metrics.py#L88)
- [`pyvisualizer.metrics.find_dead_code`](pyvisualizer/metrics.py#L153)
- [`pyvisualizer.overlays._git`](pyvisualizer/overlays.py#L23)
- [`pyvisualizer.overlays._toplevel`](pyvisualizer/overlays.py#L33)
- [`pyvisualizer.overlays.apply_churn`](pyvisualizer/overlays.py#L67)
- [`pyvisualizer.overlays.git_churn`](pyvisualizer/overlays.py#L41)
- [`pyvisualizer.retrieval.BM25Index.rank`](pyvisualizer/retrieval.py#L120)
- [`pyvisualizer.retrieval.BM25Index.search`](pyvisualizer/retrieval.py#L137)
- [`pyvisualizer.retrieval.build_bm25`](pyvisualizer/retrieval.py#L142)
- [`pyvisualizer.retrieval.derive_seeds`](pyvisualizer/retrieval.py#L189)
- [`pyvisualizer.retrieval.function_source`](pyvisualizer/retrieval.py#L75)
- [`pyvisualizer.retrieval.rank_seeds`](pyvisualizer/retrieval.py#L219)
- [`pyvisualizer.retrieval.tokenize`](pyvisualizer/retrieval.py#L64)
- [`pyvisualizer.review._risk_lines`](pyvisualizer/review.py#L183)
- [`pyvisualizer.review.analyze_review`](pyvisualizer/review.py#L50)
- [`pyvisualizer.review.render_markdown`](pyvisualizer/review.py#L112)
- [`pyvisualizer.review.render_text`](pyvisualizer/review.py#L198)
- [`pyvisualizer.serializers.c4.generate_c4_dsl`](pyvisualizer/serializers/c4.py#L27)
- [`pyvisualizer.serializers.json_graph.graph_to_dict`](pyvisualizer/serializers/json_graph.py#L65)
- [`pyvisualizer.serializers.json_graph.graph_to_json`](pyvisualizer/serializers/json_graph.py#L162)
- [`pyvisualizer.setup_init._action_readme`](pyvisualizer/setup_init.py#L232)
- [`pyvisualizer.setup_init._record_features`](pyvisualizer/setup_init.py#L205)
- [`pyvisualizer.setup_init.run_init`](pyvisualizer/setup_init.py#L305)
- [`pyvisualizer.utils.file_discovery.analyze_project`](pyvisualizer/utils/file_discovery.py#L151)
- [`pyvisualizer.utils.file_discovery.find_project_python_files`](pyvisualizer/utils/file_discovery.py#L38)
- [`pyvisualizer.utils.file_discovery.get_module_name`](pyvisualizer/utils/file_discovery.py#L96)
- [`pyvisualizer.visualizers.d3.generate_d3_visualization`](pyvisualizer/visualizers/d3.py#L18)
- [`pyvisualizer.visualizers.html.generate_html_visualization`](pyvisualizer/visualizers/html.py#L29)
- [`pyvisualizer.visualizers.mermaid._categorize_methods`](pyvisualizer/visualizers/mermaid.py#L301)
- [`pyvisualizer.visualizers.mermaid._rollup`](pyvisualizer/visualizers/mermaid.py#L39)
- [`pyvisualizer.visualizers.mermaid.create_interactive_html`](pyvisualizer/visualizers/mermaid.py#L336)
- [`pyvisualizer.visualizers.mermaid.generate_github_mermaid`](pyvisualizer/visualizers/mermaid.py#L82)
- [`pyvisualizer.visualizers.mermaid.generate_styled_mermaid`](pyvisualizer/visualizers/mermaid.py#L114)
</details>
<!-- pyvisualizer:end -->

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PyVisualizer is MIT-licensed.

---

## Author

**Syed Mohd Haider Rizvi**
[Portfolio](https://haider1998.github.io/) · [LinkedIn](https://www.linkedin.com/in/s-m-h-rizvi-0a40441ab/) · [GitHub](https://github.com/haider1998)
