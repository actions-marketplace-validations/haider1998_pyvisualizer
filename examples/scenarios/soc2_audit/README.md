# Fixture: the audit deadline (layered app with a real violation)

A billing service split into three layers — `api` → `domain` → `infra`. The
rule the team agreed on is that **`domain` must never call `api`** (business
logic shouldn't reach back up into the transport layer). One function breaks
that rule on purpose, so the walkthrough in
[`docs/use-cases/soc2-audit.html`](../../../docs/use-cases/soc2-audit.html) can
show a **real** gate failure with an exact `file:line`, plus a clean pass once
the rule is respected.

```bash
# Fails with the exact offending call site:
py-code-visualizer check examples/scenarios/soc2_audit \
    --layers api domain infra --forbid 'domain -> api'

# The same command a CI job runs; deterministic committed diagrams are the
# dated audit trail.
py-code-visualizer visualize examples/scenarios/soc2_audit -o architecture.html
```
