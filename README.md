# Guided Local Intelligence (GLI)

Guided Local Intelligence is a Rust CLI that helps small local LLMs handle complex work by wrapping them in a structured agent loop instead of relying on a single raw prompt. It sits on top of the local `Agent-B` framework and uses a local Ollama-compatible model for reasoning.

## What It Does

GLI adds orchestration around small models, especially in the 1B to 3B range:

- Clarify the task before planning
- Build a short numbered plan
- Execute steps with tool-using agents
- Verify and synthesize results
- Reflect and optionally loop for refinement

Current runtime flow:

```text
User Input
  -> CLARIFY
  -> PLAN
  -> EXECUTE
  -> VERIFY
  -> SYNTHESIZE
  -> REFLECT
  -> Final Output
```

The main design goal is to improve task alignment, reduce hallucinated reasoning, and make local models more reliable on general multi-step tasks such as research, local file work, technical documentation, structured investigation, and other instruction-following workflows.

## Architecture

GLI is the guidance layer in a larger stack:

```text
User / CLI
  -> GLI Guidance Engine
  -> Agent-B Orchestration Framework
  -> Local LLM Runtime (Ollama-compatible)
  -> Tools / Filesystem / Web Search
```

Core project components:

- `src/main.rs`: CLI entrypoint and run banner/output
- `src/config.rs`: command-line configuration
- `src/guidance_engine.rs`: clarification stage, progressive loop, progress persistence, report writing
- `src/agents.rs`: planner, executor, verifier, synthesizer, clarifier, and reflection agent builders
- `src/tools.rs`: repo scanning, file reading, language detection, memory, and web search tools
- `src/context_summarizer.rs`: compact summaries used between stages

## Key Features

- Clarification-first workflow before any planning or execution
- Short planning and execution cycles designed for small local models
- File inspection tools exposed to agents when local context is needed
- Shared memory between steps for important findings
- Progress persistence and resume support
- Optional path-aware execution for tasks that depend on local files

## Requirements

- Rust toolchain with Cargo
- Ollama-compatible local model endpoint
- Local checkout of `Agent-B` at `../Agent-B`

The Cargo manifest currently depends on:

```toml
agent_b = { path = "../Agent-B", package = "Agent-B" }
```

So this repository expects to live beside the `Agent-B` repository.

## Build

```bash
cargo build
```

The binary name is `gli`.

## Usage

Basic form:

```bash
cargo run -- "write a rollout plan for migrating our auth flow"
```

Using a project path:

```bash
cargo run -- "summarize the structure of this project" --path .
```

Using a specific model:

```bash
cargo run -- "draft release notes from this project" --model qwen2.5:1.5b --path .
```

Built binary:

```bash
./target/debug/gli "fix critical runtime issues" --path /path/to/project
```

### CLI Options

- Positional `task`: the task GLI should perform
- `--model`: model name, default `qwen2.5:1.5b`
- `--ollama_url`: API base URL, default `http://localhost:11434/v1`
- `--max-loops`: maximum refinement loops, default `3`
- `--max-steps`: maximum agent steps per planner/executor run, default `17`
- `--path`, `-p`: optional local filesystem context
## Clarification Stage

One of the main implemented improvements is the clarification stage that runs before the normal loop. Instead of planning immediately from a vague prompt, GLI first produces:

- `Understanding`
- `Goals`
- `Scope`
- `Questions`

It then shows a compact plan preview and asks the user to confirm or clarify. If the user adds more detail, GLI replans with those notes before execution. This reduces plan misalignment and avoids wasting cycles on the wrong task.

## Typical Use Cases

- General instruction following for small local models
- Local workspace analysis when a path is provided
- Technical documentation generation
- Structured task decomposition for local models
- Guided execution where verification and reflection matter

## Evaluation Idea

The project documents a simple comparison approach:

- Baseline: small local LLM with a single prompt
- GLI: same model with clarification, planning, execution, verification, and reflection

Suggested metrics:

- Task completion rate
- Reasoning correctness
- Hallucination reduction
- Output coherence

## Project Status

The codebase includes the main GLI loop plus the newer clarification stage. The `readme/` directory contains the original project specification, architecture notes, implementation summaries, and clarification-focused design docs that this README consolidates.

Useful source documents:

- [readme/guided_local_intelligence_project_spec.md](/home/bittu/Desktop/guided_local_intelligence/readme/guided_local_intelligence_project_spec.md)
- [readme/PROJECT_ARCHITECTURE.md](/home/bittu/Desktop/guided_local_intelligence/readme/PROJECT_ARCHITECTURE.md)
- [readme/IMPLEMENTATION_SUMMARY.md](/home/bittu/Desktop/guided_local_intelligence/readme/IMPLEMENTATION_SUMMARY.md)
- [readme/START_HERE.md](/home/bittu/Desktop/guided_local_intelligence/readme/START_HERE.md)

## Notes

- Small-model compatibility is a primary design constraint.
- The prompts are written to push models toward very small, reliable execution steps instead of broad reasoning jumps.
- Tool calls are embedded in prompts in a compact JSON format to work better with local Ollama-served models.
- The displayed startup banner in code still mentions `PLAN -> EXEC -> SYNTHESIZE -> REFLECT`, but the implemented engine includes a clarification stage and explicit verification before synthesis.
