# ADP — Agentic Decomposition Pipeline

A CLI tool that takes any complex prompt and produces complete, production-ready files
by running a 3-stage pipeline entirely through **Ollama** — no external API keys required.

## How It Works

1. **Decompose** — A large Ollama model (`gpt-oss:120b-cloud`) breaks your prompt into atomic micro-tasks with a dependency graph and few-shot examples
2. **Execute** — A small Ollama model (`qwen2.5-coder:7b`) runs each task locally, in parallel where possible, with outputs injected into downstream task prompts
3. **Assemble** — The large model stitches all outputs into complete, production-ready files

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

# Plain output (no TUI — for CI/scripting)
uv run adp --no-tui "Generate a pyproject.toml for a Python CLI tool"
```

## CLI Options

| Option | Description |
|---|---|
| `PROMPT` | Task prompt (omit for interactive TUI mode) |
| `--output`, `-o` | Output directory (default: `./adp_output`) |
| `--model`, `-m` | Override local Ollama model |
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

## Architecture

```
User Prompt
     │
     ▼ (large Ollama model — once)
Decompose → Task Plan (dependency graph, few-shot prompts)
     │
     ▼ (small Ollama model — many times, parallel)
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
prompt — only a narrow instruction with 3–5 concrete examples.
