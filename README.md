# GLI — Guided Local Intelligence

A CLI tool that takes any complex prompt and produces complete, production-ready files
by running a 3-stage pipeline entirely through **Ollama** — no external API keys required.

<img width="1887" height="975" alt="Screenshot_2026-04-18_20-28-45" src="https://github.com/user-attachments/assets/2a845b1a-d0ea-434f-a017-ab2f0ec43658" />


## How It Works

1. **Decompose** — A large Ollama model (`gpt-oss:120b-cloud`) breaks your prompt into atomic micro-tasks, file paths, and implementation contracts with a dependency graph and few-shot examples
2. **Execute** — Small Ollama models write the actual code locally, one tiny task at a time, with outputs injected into downstream task prompts
3. **Assemble** — The large model stitches those local outputs into complete, production-ready files without inventing new logic

## Setup

```bash
# Ensure you have uv installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Pull required Ollama models
ollama pull gpt-oss:120b-cloud
ollama pull qwen2.5-coder:7b

# Install dependencies
uv sync

# Copy and edit env vars (optional — defaults work out of the box)
cp .env.example .env
```

## Usage

```bash
# Interactive TUI mode
uv run adp

# Single prompt
uv run adp "Create a FastAPI orders API with 5 endpoints"

# With options
uv run adp --output ./my_project --debug "Write pytest tests for this module"

# Mix and match planner/coder/general models
uv run adp \
  --cloud-model gpt-oss:120b-cloud \
  --coder-model qwen2.5-coder:7b \
  --general-model qwen2.5:7b \
  "Refactor this package into a CLI"

# Plain output (no TUI — for CI/scripting)
uv run adp --no-tui "Generate a pyproject.toml for a Python CLI tool"
```

Model names now live in [adp/config.py](/home/bittu/Desktop/guided_local_intelligence/adp/config.py).
Defaults are defined there, and you can override them per run with CLI flags or env vars:
`CLOUD_MODEL`, `LOCAL_CODER_MODEL`, `LOCAL_GENERAL_MODEL`.

## CLI Options

| Option | Description |
|---|---|
| `PROMPT` | Task prompt (omit for interactive TUI mode) |
| `--output`, `-o` | Output directory (default: `./output`) |
| `--model`, `-m` | Override both local Ollama models |
| `--cloud-model` | Override the cloud/planner model |
| `--coder-model` | Override the local coder model |
| `--general-model` | Override the local general model |
| `--no-tui` | Plain text output (for scripting/CI) |
| `--debug` | Print all system prompts and raw outputs |
| `--version` | Show version |

## Running Tests

```bash
# Unit tests (no Ollama required)
uv run pytest tests/test_graph.py tests/test_validator.py tests/test_decomposer.py tests/test_executor.py -v

# All tests
uv run pytest -v
```

## MCP Servers

ADP can expose external tools to the decomposer and executor through `mcp_servers.toml`.
This repo now includes a free web-search MCP server configuration that does not require an API key:

```toml
[[servers]]
name      = "web_search"
transport = "stdio"
command   = "npx"
args      = ["-y", "open-websearch@latest"]
[servers.env]
MODE = "stdio"
DEFAULT_SEARCH_ENGINE = "startpage"
ALLOWED_SEARCH_ENGINES = "startpage,duckduckgo"
```

This uses `open-websearch`, which supports no-key web search and content retrieval over MCP.
It requires `node`/`npm` with `npx` available on the machine. `startpage` is set as the
default because DuckDuckGo HTML search can return `403` for some environments.

## Architecture

```
User Prompt
     │
     ▼ (large Ollama model — once)
Decompose → Task Plan (dependency graph, few-shot prompts)
     │
     ▼ (small Ollama model — many times, sequential)
Execute → Context Dict (key → output per task)
     │
     ▼ (large Ollama model — once)
Assemble → {filename: content}
     │
     ▼
Write → Files on disk
```

The key mechanism is **context injection** — the output of each task is injected directly
into the system prompt of tasks that depend on it. The small model never sees the original
prompt — only a narrow instruction with 3–5 concrete examples and enough upstream structure
to implement one precise code fragment at a time.
