# ADP — Agentic Decomposition Pipeline

A CLI tool that takes complex prompts and produces complete outputs through a local-first
micro-task pipeline running entirely through **Ollama** — no external API keys required.

## How It Works

1. **Decompose** — A large Ollama model breaks your prompt into atomic micro-tasks with explicit task kinds, validator hints, and dependency ordering
2. **Validate Plan** — The plan is checked for duplicate ids, missing dependencies, unresolved placeholders, invalid final outputs, and prompt-size issues before any local execution begins
3. **Execute** — Local models run each task with context injection, task-aware routing, deterministic validation, and bounded retries
4. **Repair** — Invalid task outputs are repaired with a focused correction pass instead of blindly re-running the same prompt
5. **Assemble** — The large model combines only validated fragments into the final response or files

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
     ▼
Plan Validation → fail fast on bad placeholders / keys / groups
     │
     ▼ (small Ollama model — many times, parallel)
Execute → deterministic validation → targeted repair if needed
     │
     ▼ (large Ollama model — once)
Assemble → {filename: content}
     │
     ▼
Write → Files on disk
```

The key mechanisms are:

- **Context injection** — each downstream task receives only the upstream outputs it depends on
- **Task-aware routing** — extraction, codegen, summarization, and critic-style tasks can use different local models
- **Deterministic validation** — outputs are checked by anchor type, optional validator rules, and Python syntax where applicable
- **Repair before failure** — invalid outputs get a focused correction pass before the task is marked failed
- **Disk cache for deterministic tasks** — repeated runs with the same filled prompt can reuse validated local outputs

Execution logs now include per-run evaluation metrics such as success rate, retries, and completion counts by task kind.
