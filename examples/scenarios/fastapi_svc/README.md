# Fixture: fastapi_svc

A FastAPI-*shaped* service in plain Python — decorated route handlers →
services → repositories — used by the walkthrough at
[`docs/for/fastapi.html`](../../../docs/for/fastapi.html). py-code-visualizer is
pure AST analysis, so FastAPI itself isn't needed to map a FastAPI-style
codebase; the local `@get`/`@post` decorators exercise the same decorator
metadata collection a real app hits.

```bash
py-code-visualizer impact create_order examples/scenarios/fastapi_svc
py-code-visualizer check examples/scenarios/fastapi_svc --fail-on-cycles
py-code-visualizer context examples/scenarios/fastapi_svc --focus create_order
```
