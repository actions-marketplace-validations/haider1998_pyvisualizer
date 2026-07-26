# AI Context Guide — Cut Token Costs by 97%

Instead of pasting your whole codebase into an AI chat, generate a small, verified
slice of it — the exact functions the task touches, with every call edge traced to a
`file:line`. On a real 60-file project this cuts context from **139,697 tokens to
~4,000** and makes the AI more accurate, not less.

---

## Install

```bash
pip install py-code-visualizer
```

That's it. No API keys, no accounts, no code executed.

---

## The three commands

### 1 — You know what you're trying to do (most common)

Describe the task in plain English. pyvisualizer maps it to seed functions via text
search, then walks the verified call graph to pull in everything that matters:

```bash
py-code-visualizer context . --task "add retry logic to the HTTP client" --budget-tokens 4000
```

Copy the output. Paste it into Claude, ChatGPT, or Cursor **before** your question.
The AI now has the right 4,000 tokens instead of 140,000 guessed ones.

---

### 2 — You know the function name

```bash
py-code-visualizer context . --focus send_request --budget-tokens 4000
```

Use `--focus` when you already know the entry point. You can combine both flags to
lock in a seed while still describing the task:

```bash
py-code-visualizer context . --focus send_request --task "add retry on 429" --budget-tokens 4000
```

---

### 3 — Wire it in so your agent always has it (one-time setup)

```bash
py-code-visualizer export --for-ai .
```

This writes `ARCHITECTURE.json` and injects a section into `AGENTS.md` — the file
Claude Code, Copilot Workspace, and Cursor all read automatically. From that point,
every agent session starts with verified architecture facts instead of re-deriving
the codebase from scratch.

Keep it fresh in CI:

```bash
py-code-visualizer export --check .   # fails if committed graph is stale
```

---

## What the output looks like

```
# Context Pack — myproject

- Task: add retry logic to the HTTP client
- Included functions: 7
- Estimated size: ~4,000 tokens (vs ~139,697 tokens full source) — 97% smaller

## Seeds (task → code, best match first)
- `client.send_request` — 182.3 · symbol
- `client._build_headers` — 61.1 · bm25

## Function bodies (top-ranked, within budget)

### `client.send_request`
```python
def send_request(self, method, url, **kwargs):
    response = self._session.request(method, url, **kwargs)
    response.raise_for_status()
    return response
```

## Functions
- `client.send_request(method, url, **kwargs)` — client.py:42  ← full source above
- `client._build_headers(extra)` — client.py:28
- `auth.sign_request(request)` — auth.py:15
  ...

## Verified calls (caller → callee · confidence · file:line)
- `client.send_request` → `client._build_headers` · resolved · client.py:44
- `client.send_request` → `auth.sign_request` · resolved · client.py:47
  ...
```

Every function is real. Every call edge is parsed from the AST and traceable to its
exact source line. Circular dependencies are surfaced automatically. Nothing is
guessed or hallucinated.

---

## Optional: MCP server (real-time, mid-task)

If you use Claude Code or Cursor, the MCP server lets the agent query the verified
graph at the exact moment it needs context — no manual copy-paste:

```bash
pip install 'py-code-visualizer[mcp]'   # Python 3.10+ required
pyvisualizer-mcp .
```

Then add to `.mcp.json` (Claude Code) or your MCP client settings:

```json
{
  "mcpServers": {
    "pyvisualizer": {
      "command": "pyvisualizer-mcp",
      "args": ["/path/to/your/project"]
    }
  }
}
```

Three tools become available to the agent:

| Tool | What it does |
|---|---|
| `search_code` | Lexical search over all functions by name or content |
| `context_pack` | Budget-bounded verified pack, seeded by task description |
| `impact` | Blast radius — transitive callers/callees for any function |

---

## CLI flags (context command)

```
py-code-visualizer context <path> [options]

  --task "<prose>"        Describe the task; pyvisualizer finds the seed functions
  --focus <fn>            Name a specific function as the starting point
  --budget-tokens <n>     Hard cap on output size (default: 8000)
  --strategy text         BM25-only seed (default, fastest, best recall)
  --strategy hybrid       BM25 + graph expansion (wider neighborhood)
  --no-bodies             Signatures only — cuts token use further
  --repo-url <url>        Add GitHub links to every function (for clickable refs)
```

**Tip:** start with `--strategy text` and `--budget-tokens 4000`. If the pack
misses something obvious, bump the budget to 8000 or switch to `--strategy hybrid`.

---

## Measured results

Evaluated on **httpx** (real open-source project, 1,076 functions, real closed bug):

| Approach | Tokens | Claude Opus 5 cost | Relevant signal/1k tokens |
|---|---|---|---|
| Full source | 139,697 | $2.10 | 1× (baseline) |
| Keyword grep | 24,652 | $0.37 | 6× |
| **pyvisualizer `--task`** | **~4,000** | **$0.06** | **35×** |

97% fewer tokens. 35× more relevant signal per token. The 97% saving is
model-agnostic — it scales with whatever model price you're paying.

Detailed methodology: [`docs/use-cases/agent-context.html`](https://haider1998.github.io/pyvisualizer/use-cases/agent-context.html)

---

## Troubleshooting

**"No functions found"** — make sure `<path>` points to a directory with `.py` files.
Run `py-code-visualizer visualize <path> -o map.html` first to confirm the graph builds.

**Pack is larger than expected** — lower `--budget-tokens` or add `--no-bodies`.

**Missing a function I expect** — try `--strategy hybrid` or add it explicitly with
`--focus` in addition to `--task`.

**MCP server not connecting** — check that the path in `args` is the project root
(the directory containing your `.py` files), and that you're on Python 3.10+.
