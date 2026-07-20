# Fixture: ml_pipeline

An ML-pipeline-*shaped* codebase in plain Python — `run → ingest → features →
train → evaluate`, plus the thing every real ML repo accumulates: **orphaned
experiment code nothing calls anymore**. Used by the walkthrough at
[`docs/for/ml-pipelines.html`](../../../docs/for/ml-pipelines.html). Pure AST
analysis — no ML libraries needed to map an ML-style codebase.

```bash
py-code-visualizer visualize examples/scenarios/ml_pipeline -o pipeline.html
py-code-visualizer check examples/scenarios/ml_pipeline --dead-code
py-code-visualizer context examples/scenarios/ml_pipeline --focus train_model
```
