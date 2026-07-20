# Fixture: the orphan monolith

A deliberately under-documented reporting service — the kind of thing five
contractors build and then leave behind. It has a real entry point
(`app.cli:run`), a couple of genuinely dead functions no live path reaches, and
two same-named helpers that create an honestly *ambiguous* call.

It exists so the walkthrough in
[`docs/use-cases/orphan-monolith.html`](../../../docs/use-cases/orphan-monolith.html)
can show **real** `visualize`, `health`, and `check --dead-code` output — nothing
in that page is staged.

```bash
py-code-visualizer visualize examples/scenarios/orphan_monolith -o map.html
py-code-visualizer health examples/scenarios/orphan_monolith
py-code-visualizer check examples/scenarios/orphan_monolith --dead-code
```
