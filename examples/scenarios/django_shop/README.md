# Fixture: django_shop

A Django-*shaped* shop application in plain Python — `urls → views → services →
models` — used by the walkthrough at
[`docs/for/django.html`](../../../docs/for/django.html). py-code-visualizer is
pure AST analysis, so it doesn't need Django installed to map a Django-style
codebase; this fixture keeps CI dependency-free while exercising the same
layered call structure a real project has.

```bash
py-code-visualizer visualize examples/scenarios/django_shop -o shop.html
py-code-visualizer impact checkout examples/scenarios/django_shop
```
