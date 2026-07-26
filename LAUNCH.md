# Launch Kit

Ready-to-post drafts for the human-only discovery channels, plus a monthly
measurement checklist. **You post these yourself, from your own accounts** —
community rules require a real human, and honesty is the whole brand. Nothing
here is auto-posted. Edit freely; every number below comes from
[`docs/benchmarks.json`](docs/benchmarks.json) — if you change the code, re-run
`python benchmarks/bench.py` and update the figures before posting.

> Rule of thumb for all of these: lead with the honest, specific thing the tool
> does that others don't (parsed-not-guessed, `file:line` on every edge,
> deterministic, CI-able, agent context). Never disparage competitors; link the
> [honest comparison](https://haider1998.github.io/pyvisualizer/compare.html) and
> let readers judge.

---

## 1. Show HN (news.ycombinator.com/submit)

HN wants substance and a working demo, not marketing. Keep the title plain.

**Title:**
```
Show HN: Deterministic call graphs for Python – every edge traceable to a file:line
```

**URL:** `https://github.com/haider1998/pyvisualizer`

**First comment (post immediately after submitting):**
```
I kept asking LLMs to "diagram my repo" and getting confident, subtly-wrong
pictures — invented calls, missing modules, a different answer every time. So I
built the opposite: a static analyzer that builds the call graph from Python's
AST and refuses to guess.

- Every edge is traceable to a file:line. A call it can't resolve to exactly one
  target is tagged "ambiguous" with its candidates kept — never silently picked.
- Output is deterministic (byte-identical across runs), so it lives in CI: fail
  the build on new circular dependencies, enforce layer rules, post a PR review
  comment with the blast radius of each change.
- The interactive HTML is a single self-contained file — zero network requests,
  no code executed — so it's safe on any codebase and works air-gapped.
- There's also a "context" command that hands an AI agent a small verified slice
  of the architecture instead of the whole repo.

Measured on a deterministic 98,669-line synthetic project: full graph in ~4.9s,
100% of edges carry file:line, two runs byte-identical (SHA-256 equal). Numbers +
methodology: https://haider1998.github.io/pyvisualizer/facts.html

Try it in the browser (nothing uploaded):
https://haider1998.github.io/pyvisualizer/playground.html

It's Python-only and static, so dynamic dispatch has real limits — I'd genuinely
like feedback on the resolution edge cases and where the ambiguous-tagging is too
conservative or not conservative enough.
```

**Timing:** weekday, ~8–10am US Eastern tends to do best. Reply to every comment.

---

## 2. r/Python (reddit.com/r/Python)

r/Python allows sharing your own tools but the mods and readers punish anything
that smells like an ad. Follow the "I made a thing, here's what's hard about it,
tell me where it breaks" register. Check the current rules/flair before posting;
Thursday is often "self-promotion"-friendly but verify.

**Title:**
```
I built a static call-graph tool for Python that flags what it can't resolve instead of guessing
```

**Body:**
```
Static-analysis tools that draw call graphs have to make a choice when a call is
ambiguous (two methods named save(), dynamic dispatch, etc.): guess, or admit it.
Most guess. I wanted one that admits it, because I wanted the output to be
trustworthy enough to gate CI on.

What it does:
- Builds the call graph from the AST (no code executed, no imports run).
- Tags every edge resolved / inherited (via MRO) / ambiguous, and keeps the full
  candidate list for ambiguous ones. Every edge has a file:line.
- Deterministic output → self-healing README diagram, PR review comments with
  blast radius, cycle/layer CI gates, and a JSON/context export for AI agents.
- Self-contained interactive HTML (no CDN, offline).

Works on any Python project — I wrote up stack-specific walkthroughs for Django,
FastAPI, and ML pipelines with runnable fixtures.

Honest limitations: Python-only, static (so it won't follow runtime-registered
callbacks it can't see structurally), and on tiny projects the "context pack" is
no smaller than the source — the win scales with repo size.

Repo: https://github.com/haider1998/pyvisualizer
Browser demo: https://haider1998.github.io/pyvisualizer/playground.html

Would love feedback on the resolution logic specifically — where does it guess
when it shouldn't, or bail when it could resolve?
```

---

## 3. dev.to article draft

Long-form is where AI assistants and search both feed. Publish under your account
with tags `#python #architecture #devtools #ai`.

**Title:** `Your architecture diagram is probably lying to you`

**Outline / draft:**
```
## Your architecture diagram is probably lying to you

Every architecture diagram I've inherited has been wrong in the same three ways:
it's out of date, it's someone's mental model rather than the code, or an LLM
drew it and invented half the arrows.

The fix isn't a better artist. It's to stop drawing and start parsing.

### Guessing vs. proving
[Explain: an LLM produces the architecture it *expects*; a parser produces the
one that *exists*. Show a real ambiguous case and how guessing invents an edge.]

### Every arrow should click through to a line of code
[Show the file:line provenance; the interactive HTML inspector.]

### If it's deterministic, it can live in CI
[Show: self-healing README, PR review comment with blast radius, cycle gate.
Paste real command output from the repo fixtures.]

### The AI angle: point your agent at the graph, not the repo
[Show the context command and the 97%-smaller measured number; explain fewer
tokens + no hallucinated structure.]

### Try it on your own code in 30 seconds
pip install py-code-visualizer && py-code-visualizer visualize .
[Link the playground and the per-stack guides.]

### Honest limits
[Python-only, static, dynamic dispatch caveats — link the comparison page.]
```
Paste only real output (run the commands against `examples/scenarios/*`). Link
`facts.html` for every number.

---

## 4. Awesome-list PRs (one-line entries)

Submit small, on-topic PRs adding the tool to the relevant section. Read each
list's contribution guide first; add alphabetically where required.

- **awesome-python** (vinta/awesome-python) → "Code Analysis" section:
  ```
  - [py-code-visualizer](https://github.com/haider1998/pyvisualizer) - Deterministic, AST-verified call graphs for Python with file:line provenance, CI gates, and AI-agent context export.
  ```
- **analysis-tools-dev/static-analysis** → Python section (this list is
  specifically for static-analysis tools, a strong fit):
  ```
  - [py-code-visualizer](https://github.com/haider1998/pyvisualizer) - Builds a deterministic call graph from the AST; flags unresolved calls as ambiguous instead of guessing; exports interactive HTML, Mermaid, JSON, and C4.
  ```
- **awesome-static-analysis** (mirror/related) → Python section, same entry.

One PR per list, each genuinely on-topic. Don't mass-submit.

---

## 5. Listicle outreach (the "best code visualization tools" pages)

Several 2026 roundups rank for our keywords and don't list us yet. A short,
factual note (issue, PR to their repo if open-source, or contact form) — not a
pitch:

**Template:**
```
Subject: A Python call-graph tool for your "code visualization tools" roundup

Hi — your <year> roundup of code visualization tools is a great reference. You
might consider py-code-visualizer (MIT, https://github.com/haider1998/pyvisualizer)
for the Python/static-analysis entries. What makes it distinct from pyan/code2flow/
pydeps: it's deterministic (byte-identical output), tags unresolvable calls as
ambiguous instead of guessing, puts a file:line on every edge, and runs as a CI
gate. There's an honest feature comparison here if useful:
https://haider1998.github.io/pyvisualizer/compare.html
Happy to answer anything. No worries if it's not a fit.
```
Targets found in research (verify they're still relevant before reaching out):
repowise.dev's comparison, codelayers.ai's 2026 guide, dev.to code-tools posts.

---

## 6. Monthly measurement checklist (no telemetry — external signals only)

The tool ships zero telemetry, so measure from the outside. First working day of
each month:

- [ ] **Google Search Console** (already verified for the site): note top queries,
      impressions, and average position. Are the persona/intent pages
      (`for/*`, `solve/circular-imports`) picking up impressions? Submit the
      sitemap again if new pages aren't indexed.
- [ ] **PyPI downloads**: `pip install pypistats && pypistats recent py-code-visualizer`
      — record monthly downloads; registry growth is slow (6–18 months), so track
      the trend, not the absolute.
- [ ] **GitHub**: stars, and Insights → Traffic (views/clones, top referrers) —
      referrers tell you which channel actually worked.
- [ ] **AI-answer spot check**: ask ChatGPT / Claude / Perplexity a few real
      queries ("tool to visualize a Django project's call graph", "find circular
      dependencies in Python CI", "give an AI agent context about a Python
      codebase") and note whether we're cited and how we're described. This is the
      GEO scoreboard.
- [ ] **Listicles**: check whether the roundup pages you contacted added us.
- [ ] Log one line per month somewhere (a `GROWTH.md` or a note) so the trend is
      visible over quarters.

Success signals, in rough order of leading→lagging: AI answers start citing us →
long-tail impressions rise in GSC → GitHub referrer traffic from HN/Reddit/dev.to
→ PyPI downloads trend up → listicles add us.
