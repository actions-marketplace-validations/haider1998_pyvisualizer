# py-code-visualizer 2.0 — The Ground Truth Engine

*A manifesto, not a changelog.*

---

## The Hallucination Tax

Right now, somewhere, a developer is pasting their repo into a chat window and
asking a model to "diagram the architecture." It answers instantly, confidently,
beautifully. It also invents a dependency that doesn't exist, quietly omits the
module that didn't fit the context window, and — run it again — draws something
different.

That diagram ships. It goes in the onboarding doc. It informs the refactor. And
every decision made on top of it inherits a lie that *looked* like an answer.

This is the hallucination tax, and the whole industry is paying it. Not because
LLMs are bad — they're extraordinary — but because we've been asking a
probability engine to do a job that requires **proof**.

## We chose proof over vibes

py-code-visualizer does one thing with total conviction: it tells you the truth
about how your Python actually calls itself, and it can show you the exact line
that proves each claim.

- **Parsed, not guessed.** Every edge in the graph comes from your AST. If two
  functions don't call each other, no arrow appears — ever.
- **`file:line` on every edge.** Click any relationship in the interactive map
  and see the exact source location. Provenance isn't a feature here; it's the
  point.
- **Deterministic.** Two runs on unchanged code produce byte-identical output.
  That single property is what turns a diagram from a decoration into
  infrastructure — diffable, gate-able, committable.
- **Honest about doubt.** When a call genuinely can't be resolved to one target,
  we don't flip a coin and pretend. We tag it `ambiguous` and keep every
  candidate. A tool that markets ground truth cannot afford to bluff.
- **Nothing leaves your machine.** No execution, no network, no upload. The
  interactive HTML makes zero external requests. Air-gap it. Ship it to a SOC 2
  auditor. It's just math over your source.

## What 2.0 does

- **`visualize`** — a self-contained interactive map (HTML), plus Mermaid, JSON,
  and C4/Structurizr export.
- **`readme`** — self-healing architecture diagrams that a CI bot keeps in sync,
  committing *only* when the architecture truly changed.
- **`diff`** — PR reports that show the real structural delta and flag newly
  introduced circular dependencies.
- **`check`** — CI gates for cycles and layering rules, enforced at call-graph
  level (stricter than any import linter).
- **`impact`** — blast radius before you refactor: "this touches 43 transitive
  callers across 6 modules."
- **`health`** — an A–F architecture grade your whole team can see and defend.
- **`export --for-ai`** — verified ground truth for your coding agents. Point
  them at the graph, not the repo.

## The one command

```bash
pip install py-code-visualizer && py-code-visualizer visualize .
```

No signup. No server. No telemetry. Open the HTML and watch your own codebase
map itself — correctly — in two seconds.

The era of confidently-wrong architecture is over. Diagram from proof.

— **[py-code-visualizer](https://github.com/haider1998/pyvisualizer)** · MIT ·
built for developers who need to be right.
