# Integrations

PyVisualizer is designed to live inside the workflows you already run. Every
command is pure AST analysis — no code is imported or executed — so it is safe
to run in CI, in pre-commit, and in air-gapped environments.

## Configuration (`pyproject.toml`)

Declare defaults once so CI/pre-commit invocations are flag-free:

```toml
[tool.pyvisualizer]
exclude = ["tests", "migrations"]
max_nodes = 120
target = "README.md"
detail = "module"          # module | class | function

[tool.pyvisualizer.rules]
layers = ["api", "domain", "infra"]
forbid = ["domain -> api", "domain -> infra"]
```

## GitHub Actions

### Self-healing README

```yaml
- uses: haider1998/PyVisualizer@v2
  with:
    mode: readme
    target: README.md
```

### Architecture gate (fail on cycles / layer violations)

```yaml
- uses: haider1998/PyVisualizer@v2
  with:
    mode: gate
    fail-on-cycles: 'true'
```

The bundled workflows in `.github/workflows/` show the full PR-diff-comment
pattern (base vs. head graph diff, posted as a PR comment, failing on new
circular dependencies).

## Pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/haider1998/PyVisualizer
    rev: v2.0.0
    hooks:
      - id: pyvisualizer-readme      # keep README diagram in sync
      - id: pyvisualizer-gate        # block cycles / layer violations locally
```

Both hooks are fast because they only parse the AST — nothing is imported.

## GitLab CI

```yaml
# .gitlab-ci.yml
architecture:
  image: python:3.11
  stage: test
  script:
    - pip install py-code-visualizer
    # Fail the pipeline on circular dependencies:
    - py-code-visualizer check . --fail-on-cycles --exclude tests
    # Keep the README diagram current (commit via a downstream job / bot):
    - py-code-visualizer readme . --target README.md
  artifacts:
    paths:
      - README.md
```

For merge-request diffs, generate `base.json` on the target branch and
`head.json` on the source branch, then `py-code-visualizer diff base.json
head.json` and post the Markdown to the MR via the GitLab API.

## Feeding the graph to AI tools

```bash
py-code-visualizer export --for-ai .   # writes ARCHITECTURE.json + ARCHITECTURE.md
```

Point your agent (Cursor, Claude, etc.) at the verified graph instead of asking
it to re-derive the architecture from raw source — deterministic ground truth,
not a guess.
