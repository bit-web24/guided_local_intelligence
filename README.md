# GLI — Guided Local Intelligence

A CLI tool that takes any complex prompt and produces complete, production-ready files
by running a 3-stage pipeline entirely through **Ollama** — no external API keys required.

<img width="1887" height="975" alt="Screenshot_2026-04-18_20-28-45" src="https://github.com/user-attachments/assets/2a845b1a-d0ea-434f-a017-ab2f0ec43658" />

## How It Works

GLI uses an innovative **context injection** mechanism to reliably generate code using local models:

1. **Decompose** — A large Ollama model (`gpt-oss:120b-cloud`) breaks your prompt into atomic micro-tasks, file paths, and implementation contracts with a dependency graph and few-shot examples
2. **Execute** — Small Ollama models write the actual code locally, one tiny task at a time, with outputs injected into downstream task prompts
3. **Assemble** — The large model stitches those local outputs into complete, production-ready files without inventing new logic

The key insight: each task only sees the original prompt fragment and relevant upstream outputs, keeping context focused and manageable for local models.

## Quick Start

```bash
# Ensure you have uv installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Pull required Ollama models
ollama pull gpt-oss:120b-cloud
ollama pull qwen2.5-coder:1.5b
ollama pull qwen2.5:1.5b
ollama pull functiongemma:latest

# Install dependencies
uv sync

# Copy and edit env vars (optional — defaults work out of the box)
cp .env.example .env
```

## Usage

```bash
# Interactive TUI mode (recommended)
uv run adp

# Single prompt
uv run adp "Create a FastAPI orders API with 5 endpoints"

# With options
uv run adp --output ./my_project --debug "Write pytest tests for this module"

# Mix and match planner/coder/general models
uv run adp \
  --cloud-model gpt-oss:120b-cloud \
  --coder-model qwen2.5-coder:1.5b \
  --general-model qwen2.5:1.5b \
  "Refactor this package into a CLI"

# Plain output (no TUI — for CI/scripting)
uv run adp --no-tui "Generate a pyproject.toml for a Python CLI tool"
```

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
| `--resume` | Resume a prior run from output_dir/.gli_runs/<RUN_ID>/state.json |
| `--version` | Show version |

## Model Configuration

Model names live in [adp/config.py](/adp/config.py). Defaults are defined there, and you can override them per run with CLI flags or env vars:
`CLOUD_MODEL`, `LOCAL_CODER_MODEL`, `LOCAL_GENERAL_MODEL`.

### Default Models

- **Cloud/Planner**: `gpt-oss:120b-cloud` - Large model for decomposition and assembly
- **Local Coder**: `qwen2.5-coder:1.5b` - Small model for coding tasks
- **Local General**: `qwen2.5:1.5b` - Small model for text/extraction tasks
- **Tool Router**: `functiongemma:latest` - Tiny model for MCP tool routing

### Stage-Specific Overrides

You can override models for specific pipeline stages using environment variables:

```bash
# Use a different model for decomposition
MODEL_DECOMPOSER=gemma4:31b-cloud

# Use a smaller cloud model for assembly
MODEL_ASSEMBLER_CLOUD=ministral-3:3b-cloud

# Keep local execution fast with specific models
MODEL_EXECUTOR_CODER=qwen2.5-coder:1.5b
MODEL_EXECUTOR_GENERAL=qwen2.5:1.5b
```

See [.env.example](/.env.example) for all available overrides.

## Running Tests

```bash
# Unit tests (no Ollama required)
uv run pytest tests/test_graph.py tests/test_validator.py tests/test_decomposer.py tests/test_executor.py -v

# All tests
uv run pytest -v

# Test coverage
uv run pytest --cov=adp --cov-report=html
```

## MCP Servers

GLI can expose external tools to the decomposer and executor through `mcp_servers.toml`.
This repo includes a SerpAPI web-search MCP server configuration:

```toml
[[servers]]
name      = "web_search"
transport = "streamable_http"
url       = "https://mcp.serpapi.com/${SERPAPI_API_KEY}/mcp"
```

Set `SERPAPI_API_KEY` in your environment before running GLI. Do not commit
real API keys to `.env` or source control.

### Available MCP Servers

- **Filesystem** - Read/write local files (pre-configured to output directory)
- **Git** - Git operations (log, diff, show)
- **Web Search** - SerpAPI search via MCP
- **GitHub** - GitHub repositories, PRs, issues (requires token)
- **Custom SSE** - Connect to HTTP SSE servers

## Skills

GLI supports Claude-style planning Skills. A Skill is a directory containing
`SKILL.md` with YAML frontmatter:

```markdown
---
name: testing-code
description: Plan robust code testing workflows. Use when writing tests or fixing pytest failures.
---

# Testing Code

## Instructions

Skill instructions go here.
```

Project Skills live under `.claude/skills/<skill-name>/SKILL.md`. GLI loads
project Skills first, then `~/.claude/skills`, selects up to two relevant Skills
for the user prompt, and injects them into the decomposer as planning guidance.
Skills do not execute code and cannot override ADP's schema, dependency,
placeholder, anchor, MCP, or final-output validation rules.

This repo includes two sample Skills:

- `testing-code` for pytest and automated testing workflows.
- `writing-documentation` for READMEs, API docs, setup guides, and architecture notes.
- `websearch-to-file` for source-backed web research saved into a requested file.

## Architecture

```
User Prompt
     │
     ▼ (large Ollama model — once)
Decompose → Task Plan (dependency graph, few-shot prompts)
     │
     ▼ (small Ollama models — many times, sequential)
Execute → Context Dict (key → output per task)
     │
     ▼ (large Ollama model — once)
Assemble → {filename: content}
     │
     ▼
Write → Files on disk
```

### Key Features

- **Context Injection**: The output of each task is injected directly into the system prompt of tasks that depend on it
- **Sequential Execution**: Default mode ensures reliable context propagation for local models
- **Reflection Stage**: Optional semantic validation between execution and assembly
- **Verification Layers**: Multiple verification stages ensure quality:
  - Execution verification (all tasks complete)
  - Assembly verification (outputs match plan)
  - Write verification (files written correctly)
  - Prompt verification (outputs match user intent)

## Environment Variables

### Core Configuration
- `OLLAMA_URL` - Ollama server URL (default: `http://localhost:11434`)
- `OLLAMA_API_KEY` - Optional auth for Ollama-compatible proxies
- `OLLAMA_BEARER_TOKEN` - Alternative auth format

### Execution Control
- `EXECUTION_MODE` - `sequential` (default) or `parallel`
- `MAX_PARALLEL` - Max parallel tasks (default: 1 for sequential, 6 for parallel)
- `LOCAL_TIMEOUT` - Timeout for local model calls in seconds (default: 120)
- `CLOUD_TIMEOUT` - Timeout for cloud model calls in seconds (default: 180)

### Retry Strategy
- `MAX_RETRIES` - General retry count (default: 3)
- `DECOMPOSITION_MAX_RETRIES` - JSON parsing retries (default: 6)
- `MAX_REPLANS` - Maximum replan attempts (default: 2)
- `FINAL_ASSEMBLY_VERIFY_RETRIES` - Assembly verification retries (default: 2)
- `FINAL_WRITE_VERIFY_RETRIES` - File write retries (default: 3)

### Features
- `REFLECT_ENABLED` - Enable reflection stage (default: true)
- `REFLECT_USE_CLOUD` - Use cloud model for reflection (default: true)
- `CLARIFICATION_MAX_ROUNDS` - Max clarification questions (default: 3)
- `MCP_MAX_TOOL_RESULT_CHARS` - Max tool result chars to inject (`0` = no trimming, default: 0)

## Output

GLI creates several outputs in the specified output directory:

- **Generated Files** - The requested files from your prompt
- `.adp_execution_log.md` - Detailed execution log
- `success_artifact_*.md` - Summary of the run with inputs/outputs
- `.gli_runs/` - Run state files for resumption

## Examples

### Generate a Python API
```bash
uv run adp "Create a FastAPI REST API for a todo list with CRUD operations"
```

### Write Tests
```bash
uv run adp --output ./tests "Write comprehensive pytest tests for the calculator module"
```

### Web Research
```bash
uv run adp "Research the latest trends in AI and summarize findings in a markdown report"
```

### Generate Configuration
```bash
uv run adp --no-tui "Generate a docker-compose.yml for a web app with nginx, postgres, and redis"
```

## Troubleshooting

### Common Issues

1. **Models not found**: Ensure all required models are pulled with `ollama pull`
2. **Connection refused**: Check that Ollama is running on the configured port
3. **Context window exceeded**: Reduce task size or lower `MCP_MAX_TOOL_RESULT_CHARS`
4. **Parallel execution issues**: Use `EXECUTION_MODE=sequential` for better reliability

### Debug Mode

Use `--debug` to see all system prompts and model outputs:
```bash
uv run adp --debug "Your prompt here"
```

### Resuming Failed Runs

GLI can resume from the last successful stage:
```bash
# Find the run ID in output/.gli_runs/
uv run adp --resume <RUN_ID> "Refine the output"
```

## Development

### Project Structure
```
adp/
├── main.py              # CLI entry point
├── config.py            # Configuration and model settings
├── agent_graph.py       # LangGraph supervisor loop
├── models/
│   └── task.py          # Task and pipeline data models
├── stages/
│   ├── decomposer.py    # Stage 1: Task decomposition
│   ├── executor.py      # Stage 2: Task execution
│   ├── assembler.py     # Stage 3: File assembly
│   ├── reflector.py     # Optional semantic validation
│   └── replanner.py     # Replanning on failure
├── engine/
│   ├── cloud_client.py  # Large model client
│   ├── local_client.py  # Small model client
│   └── validator.py     # Output validation
├── tui/
│   ├── app.py          # Terminal UI
│   └── input_handler.py # User input handling
└── mcp/
    ├── client.py       # MCP client manager
    └── registry.py     # Tool registry
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run `uv run pytest -v`
6. Submit a pull request

## Documentation

- 📖 **[Quick Reference](docs/QUICK_REFERENCE.md)** - Common patterns and examples
- 🏗️ **[Architecture](docs/ARCHITECTURE.md)** - System design and components
- 🧪 **[Testing](docs/TESTING.md)** - Test strategy and guidelines
- 📚 **[API Reference](docs/API.md)** - Internal API documentation
- 🔄 **[Migration Guide](docs/MIGRATION.md)** - Migrating from ADP to GLI

See the [docs](docs/) directory for complete documentation.

## Contributing

We welcome contributions! See the [Contributing Guide](CONTRIBUTING.md) for details.

### Quick Development Setup

```bash
# Clone and setup
git clone https://github.com/your-username/guided_local_intelligence.git
cd guided_local_intelligence
uv sync

# Run tests
uv run pytest -v

# Make your changes and submit a PR!
```

## License

[Add your license here]

## Acknowledgments

- Built with [LangGraph](https://github.com/langchain-ai/langgraph) for orchestration
- Uses [Ollama](https://ollama.ai) for local model serving
- MCP integration via [Model Context Protocol](https://modelcontextprotocol.io)
- Terminal UI powered by [Rich](https://rich.readthedocs.io/) and [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/)
