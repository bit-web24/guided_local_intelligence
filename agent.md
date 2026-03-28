# Agentic Decomposition Pipeline — Agent Implementation Document

> This document is written for an AI coding agent. Read it entirely before writing a single line of code.
> Every design decision is explained. Every non-obvious choice has a reason.
> Do not deviate from the architecture described here without explicit instruction.

---

## 0. What You Are Building

A CLI tool called **`adp`** (Agentic Decomposition Pipeline) that accepts a complex user prompt and
produces complete, ready-to-use file outputs by:

1. Sending the prompt to a **cloud model (Claude)** which decomposes it into an ordered list of
   atomic micro tasks — each micro task is a self-contained system prompt with few-shot examples
   and a single output anchor
2. Executing those micro tasks using a **local model (via Ollama)** in the correct dependency
   order, with parallel execution where possible, injecting the output of each completed task
   into the system prompt of every task that depends on it
3. Sending all collected outputs back to the **cloud model** to assemble the final deliverable
4. Writing all output files to disk
5. Displaying everything through a **beautiful, Claude Code-style TUI** built with `rich` and
   `prompt_toolkit`

The cloud model is called exactly twice per pipeline run. All execution work happens locally.

---

## 1. Core Architectural Principle

**Context injection is the entire mechanism.** Each micro task has a `system_prompt_template`
field that contains `{placeholder}` variables. Before a local model executes a task, every
placeholder is replaced with the output of the upstream task that produced it. The local model
never sees the original user prompt. It only sees: a constrained instruction, 3–5 concrete
input→output examples, the injected upstream context already filled in, and the anchor word
at the end.

This is not RAG. There is no retrieval. Context is passed explicitly and deterministically.

**Each micro task system prompt has this exact structure:**

```
You are a [role]. [One-sentence scope constraint].
Reply ONLY with [format]. Nothing else.

EXAMPLES:
Input: [example input 1]
[Anchor]: [exact expected output 1]

Input: [example input 2]
[Anchor]: [exact expected output 2]

Input: [example input 3]
[Anchor]: [exact expected output 3]

---
[Injected upstream context if applicable, already filled in]
---

Input: {input_text}
[Anchor]:
```

The local model's job is to pattern-match against the examples. It does not reason.
It does not plan. It completes the anchor.

---

## 2. Tech Stack — Exact Versions

```
python              >= 3.11
anthropic           >= 0.25.0      # cloud model API (used inside LangChain)
langchain           >= 0.2.0       # LLM abstraction layer
langchain-anthropic >= 0.1.0       # ChatAnthropic integration
langchain-community >= 0.2.0       # OllamaLLM (used for non-async path)
rich                >= 13.7.0      # TUI: panels, progress, live, syntax highlight
prompt_toolkit      >= 3.0.43      # multiline input, key bindings, history
pydantic            >= 2.6.0       # data models and validation
networkx            >= 3.3         # dependency graph / topological sort
httpx               >= 0.27.0      # async HTTP for parallel Ollama calls
python-dotenv       >= 1.0.0       # .env loading
pytest              >= 8.0         # test runner
pytest-asyncio      >= 0.23.0      # async test support
```

Do NOT use LangGraph. The pipeline has a static dependency graph computed at decomposition
time — LangGraph's dynamic graph is unnecessary overhead. Use `networkx` for topological sort
and `asyncio` + `httpx` for parallel execution.

---

## 3. Project Structure

```
adp/
├── pyproject.toml
├── .env.example
├── README.md
│
├── adp/
│   ├── __init__.py
│   ├── main.py                  ← CLI entry point; wires all stages; owns TUI lifecycle
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── task.py              ← MicroTask, TaskPlan, ContextDict, PipelineResult
│   │
│   ├── stages/
│   │   ├── __init__.py
│   │   ├── decomposer.py        ← Stage 1: cloud decomposition via Claude
│   │   ├── executor.py          ← Stage 2: local parallel execution engine
│   │   └── assembler.py         ← Stage 3: cloud assembly via Claude
│   │
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── cloud_client.py      ← Anthropic API wrapper (LangChain ChatAnthropic)
│   │   ├── local_client.py      ← Ollama async/sync wrapper via httpx
│   │   ├── graph.py             ← dependency graph builder and topological sorter
│   │   └── validator.py         ← per-output-type validation and retry logic
│   │
│   ├── tui/
│   │   ├── __init__.py
│   │   ├── app.py               ← TUI controller: owns Layout, Live, all render state
│   │   ├── panels.py            ← individual panel renderers
│   │   ├── input_handler.py     ← prompt_toolkit multiline input with history
│   │   └── themes.py            ← all colors, styles, icons as named constants
│   │
│   ├── config.py                ← model names, timeouts, retry counts
│   └── writer.py                ← writes final files to output directory
│
└── tests/
    ├── test_decomposer.py
    ├── test_executor.py
    ├── test_graph.py
    ├── test_validator.py
    └── fixtures/
        ├── sample_task_plan.json
        └── sample_context.json
```

---

## 4. Data Models (`adp/models/task.py`)

These types are the contract between every module. Define them first. Nothing else can be
written without them.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    DONE     = "done"
    FAILED   = "failed"
    SKIPPED  = "skipped"   # skipped because a dependency failed


class AnchorType(Enum):
    JSON     = "JSON:"
    CODE     = "Code:"
    OUTPUT   = "Output:"
    MARKDOWN = "Markdown:"
    TOML     = "TOML:"


@dataclass
class MicroTask:
    id: str                          # "t1", "t2", etc. — unique, short
    description: str                 # human-readable, shown in TUI task list
    system_prompt_template: str      # contains {placeholders} for context injection
    input_text: str                  # the actual input text for the local model
    output_key: str                  # key written to context dict on completion
    depends_on: list[str]            # list of task ids this task depends on
    anchor: AnchorType               # token ending the prompt; signals output start
    parallel_group: int              # tasks with same group number run concurrently
    status: TaskStatus = TaskStatus.PENDING
    output: str | None = None        # populated after successful execution
    retries: int = 0                 # counts retry attempts
    error: str | None = None         # populated if status == FAILED


@dataclass
class TaskPlan:
    tasks: list[MicroTask]
    final_output_keys: list[str]     # which context keys the assembler receives
    output_filenames: list[str]      # expected output filenames (for TUI display)


# ContextDict: task output_key → task output value (plain string, already validated)
ContextDict = dict[str, str]


@dataclass
class PipelineResult:
    files: dict[str, str]            # filename → complete file content
    context: ContextDict             # full context dict for debugging
    tasks: list[MicroTask]           # final task list with all statuses and outputs
```

---

## 5. Configuration (`adp/config.py`)

```python
import os
from dotenv import load_dotenv

load_dotenv()

# Models
CLOUD_MODEL       = "claude-sonnet-4-5"
LOCAL_MODEL       = os.getenv("LOCAL_MODEL", "qwen2.5-coder:7b")
OLLAMA_BASE_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Execution
MAX_RETRIES       = 3
LOCAL_TEMPERATURE = 0.0            # always 0.0 for local — determinism is mandatory
CLOUD_TEMPERATURE = 0.2            # slight creativity allowed for decomposition only
LOCAL_TIMEOUT     = 120            # seconds per local model call
MAX_PARALLEL      = 6              # max concurrent local model calls

# TUI
HISTORY_FILE      = os.path.expanduser("~/.adp_history")
MAX_HISTORY       = 500

# Output
DEFAULT_OUTPUT_DIR = "./adp_output"
```

---

## 6. Stage 1 — Decomposer (`adp/stages/decomposer.py`)

### What it does

Sends the user's prompt to Claude with the decomposition system prompt below. Claude returns a
JSON object containing the task plan. This is parsed and validated into a `TaskPlan`.

### The hardcoded decomposition system prompt

This is the most critical prompt in the entire project. Store it as a module-level constant.
Do not make it configurable.

```
You are a task decomposition engine. You receive a complex user request and break it into
the smallest possible atomic micro tasks that together produce the complete deliverable.

RULES:
1. Each task must have exactly ONE output — one entity, one code block, one decision,
   one file section.

2. Every task's system_prompt_template MUST contain 3 to 5 EXAMPLES of exact
   input→output pairs showing the local model precisely what to produce.
   The examples must be realistic and representative of the task.
   This is NON-NEGOTIABLE — a task without examples will cause the local model to
   hallucinate unpredictably.

3. The system_prompt_template must end with ONLY the anchor word on the final line.
   The anchor word is one of: "JSON:", "Code:", "Output:", "Markdown:", "TOML:"

4. Tasks that share no dependencies must be assigned the same parallel_group integer.
   Tasks that depend on earlier tasks must have a higher parallel_group integer than
   all their dependencies.

5. The depends_on array must contain only valid task ids from the same plan.
   An empty depends_on array means the task has no dependencies.

6. The input_text field is the literal text the local model will receive as its user
   message. It must be short, specific, and self-contained.

7. The output_key must be snake_case, descriptive, and unique across the entire plan.

8. The final_output_keys array must list every output_key that the assembler needs
   to produce the final files.

9. For tasks with upstream dependencies, include the injected context BETWEEN the
   examples and the final input, using {placeholder} syntax matching the output_key
   of the dependency exactly.

ANCHOR SELECTION RULES:
- Use JSON:     when the output is a JSON object or array
- Use Code:     when the output is a code block in any programming language
- Use TOML:     when the output is TOML content
- Use Markdown: when the output is a markdown document
- Use Output:   for plain text, short answers, single values

Return ONLY a valid JSON object matching this exact schema. No prose. No explanation.
No markdown fences.

SCHEMA:
{
  "tasks": [
    {
      "id": "t1",
      "description": "human-readable label shown in UI",
      "system_prompt_template": "...",
      "input_text": "the specific input text for this task",
      "output_key": "snake_case_key",
      "depends_on": [],
      "anchor": "JSON:",
      "parallel_group": 0
    }
  ],
  "final_output_keys": ["key1", "key2"],
  "output_filenames": ["main.py", "pyproject.toml"]
}

EXAMPLE of a correct system_prompt_template for a task with NO upstream dependencies:

"You are a date extractor. Extract ONLY the date mentioned in the text.
Return ONLY a JSON object in this exact format: {\"date\": \"YYYY-MM-DD\"}
or {\"date\": null} if no date is present. Nothing else.

EXAMPLES:
Input: \"I want to fly to Delhi on Friday March 21\"
JSON: {\"date\": \"2026-03-21\"}

Input: \"Book a table for tomorrow\"
JSON: {\"date\": null}

Input: \"Schedule the meeting for April 5th 2026\"
JSON: {\"date\": \"2026-04-05\"}

Input: \"Call me at 3pm\"
JSON: {\"date\": null}

---
Input: {input_text}
JSON:"

EXAMPLE of a correct system_prompt_template for a task WITH upstream dependencies:

"You are a FastAPI endpoint writer. Write ONLY the Python function for one POST endpoint.
Use the exact schema and store code provided below. No imports. No explanation.

EXAMPLES:
Schema: class ItemCreate(BaseModel):\n    name: str\nStore: items = {}
Code: @app.post(\"/items\", status_code=201)\ndef create_item(item: ItemCreate):\n    id = str(uuid4())\n    items[id] = item.dict()\n    return {\"id\": id, **item.dict()}

Schema: class UserCreate(BaseModel):\n    email: str\nStore: users = {}
Code: @app.post(\"/users\", status_code=201)\ndef create_user(user: UserCreate):\n    id = str(uuid4())\n    users[id] = user.dict()\n    return {\"id\": id, **user.dict()}

---
Schema in use:
{schema_create}

Store in use:
{store_code}

Input: Write the POST endpoint for this resource.
Code:"
```

### Implementation

```python
import json
import re
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from adp.models.task import MicroTask, TaskPlan, AnchorType
from adp.config import CLOUD_MODEL, ANTHROPIC_API_KEY, CLOUD_TEMPERATURE

DECOMPOSER_SYSTEM_PROMPT = """...(exact prompt above)..."""


class DecompositionError(Exception):
    """Raised when Claude returns malformed JSON or a plan that fails validation."""
    pass


def decompose(user_prompt: str) -> TaskPlan:
    llm = ChatAnthropic(
        model=CLOUD_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=CLOUD_TEMPERATURE,
        max_tokens=8192,
    )
    messages = [
        SystemMessage(content=DECOMPOSER_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    last_error = None
    for attempt in range(3):
        response = llm.invoke(messages)
        raw = response.content
        clean = re.sub(r"```json\s*|\s*```", "", raw).strip()
        try:
            data = json.loads(clean)
            return _parse_task_plan(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = e
            # On retry, add the error to the conversation so Claude self-corrects
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"Your response failed to parse: {e}. Return only valid JSON matching the schema."})

    raise DecompositionError(f"Decomposition failed after 3 attempts. Last error: {last_error}")


def _parse_task_plan(data: dict) -> TaskPlan:
    tasks = []
    for t in data["tasks"]:
        tasks.append(MicroTask(
            id=t["id"],
            description=t["description"],
            system_prompt_template=t["system_prompt_template"],
            input_text=t["input_text"],
            output_key=t["output_key"],
            depends_on=t.get("depends_on", []),
            anchor=AnchorType(t["anchor"]),
            parallel_group=int(t["parallel_group"]),
        ))
    return TaskPlan(
        tasks=tasks,
        final_output_keys=data["final_output_keys"],
        output_filenames=data["output_filenames"],
    )
```

---

## 7. Dependency Graph (`adp/engine/graph.py`)

### What it does

Takes the flat list of `MicroTask` objects and produces an execution schedule: a list of groups
where each group is a list of tasks that can run in parallel, and each group must complete
before the next begins.

```python
import networkx as nx
from adp.models.task import MicroTask


def build_execution_groups(tasks: list[MicroTask]) -> list[list[MicroTask]]:
    """
    Build a list of parallel execution groups ordered by dependency.
    Group 0 runs first (no deps). Group N runs after group N-1 completes.
    Raises ValueError if a cycle is detected or group assignments are invalid.
    """
    G = nx.DiGraph()
    task_map = {t.id: t for t in tasks}

    for t in tasks:
        G.add_node(t.id)
        for dep in t.depends_on:
            if dep not in task_map:
                raise ValueError(f"Task {t.id} depends on unknown task id '{dep}'")
            G.add_edge(dep, t.id)

    if not nx.is_directed_acyclic_graph(G):
        cycles = list(nx.simple_cycles(G))
        raise ValueError(f"Dependency graph contains cycles: {cycles}")

    # Validate: each task's parallel_group must be strictly greater than all its deps
    for t in tasks:
        for dep_id in t.depends_on:
            dep = task_map[dep_id]
            if dep.parallel_group >= t.parallel_group:
                raise ValueError(
                    f"Task {t.id} (group {t.parallel_group}) depends on "
                    f"task {dep_id} (group {dep.parallel_group}). "
                    f"Dependency must be in a strictly earlier group."
                )

    groups: dict[int, list[MicroTask]] = {}
    for t in tasks:
        groups.setdefault(t.parallel_group, []).append(t)

    return [groups[k] for k in sorted(groups.keys())]


def get_downstream_ids(failed_id: str, tasks: list[MicroTask]) -> set[str]:
    """Return all task ids that depend on failed_id directly or transitively."""
    G = nx.DiGraph()
    for t in tasks:
        for dep in t.depends_on:
            G.add_edge(dep, t.id)
    if failed_id not in G:
        return set()
    return nx.descendants(G, failed_id)
```

---

## 8. Validator (`adp/engine/validator.py`)

### What it does

After a local model produces raw output, extract the content after the anchor word, then
validate it according to its anchor type. Returns `(is_valid, cleaned_output)`.

```python
import json
import re
from adp.models.task import AnchorType


def extract_after_anchor(raw_output: str, anchor: AnchorType) -> str:
    """
    Strip any preamble before the anchor. The model may echo the anchor word.
    Extract only what comes AFTER the last occurrence of the anchor.
    """
    anchor_str = anchor.value
    idx = raw_output.rfind(anchor_str)
    if idx == -1:
        return raw_output.strip()
    return raw_output[idx + len(anchor_str):].strip()


def validate(output: str, anchor: AnchorType) -> tuple[bool, str]:
    """
    Returns (is_valid, cleaned_output).
    cleaned_output strips markdown fences and trailing garbage.
    """
    if not output or not output.strip():
        return False, ""

    if anchor == AnchorType.JSON:
        clean = re.sub(r"```json\s*|\s*```", "", output).strip()
        # Trim anything after the closing brace/bracket
        match = re.search(r"(\{.*\}|\[.*\])", clean, re.DOTALL)
        if not match:
            return False, output
        try:
            json.loads(match.group(0))
            return True, match.group(0)
        except json.JSONDecodeError:
            return False, output

    if anchor == AnchorType.CODE:
        clean = re.sub(r"```\w*\n?|\n?```", "", output).strip()
        if len(clean) < 10:
            return False, output
        return True, clean

    if anchor == AnchorType.TOML:
        try:
            import tomllib
            tomllib.loads(output.strip())
            return True, output.strip()
        except Exception:
            return False, output

    # OUTPUT and MARKDOWN — non-empty check only
    return True, output.strip()
```

---

## 9. Local Client (`adp/engine/local_client.py`)

### What it does

Calls the Ollama API with a filled system prompt and input text. Uses `httpx` directly for
async calls (required for parallel execution). Temperature is always 0.0.

```python
import httpx
import asyncio
from adp.config import OLLAMA_BASE_URL, LOCAL_MODEL, LOCAL_TEMPERATURE, LOCAL_TIMEOUT


async def call_local_async(
    system_prompt: str,
    input_text: str,
    anchor_str: str,
) -> str:
    """
    Async Ollama call. Returns the raw model output string (may include preamble).
    The full prompt sent is: system_prompt (as system field) +
                             "Input: {input_text}\n{anchor_str}" (as prompt field)
    """
    full_prompt = f"Input: {input_text}\n{anchor_str}"
    payload = {
        "model": LOCAL_MODEL,
        "system": system_prompt,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": LOCAL_TEMPERATURE,
            "num_predict": 2048,
        },
    }
    async with httpx.AsyncClient(timeout=LOCAL_TIMEOUT) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
        )
        response.raise_for_status()
        return response.json()["response"]


def call_local_sync(system_prompt: str, input_text: str, anchor_str: str) -> str:
    """Synchronous wrapper. Use only in non-async contexts."""
    return asyncio.run(call_local_async(system_prompt, input_text, anchor_str))


async def check_ollama_connection() -> bool:
    """Returns True if Ollama is reachable and the configured model is available."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            return any(LOCAL_MODEL in m for m in models)
    except Exception:
        return False
```

---

## 10. Stage 2 — Executor (`adp/stages/executor.py`)

### What it does

This is the core of the pipeline. It takes a `TaskPlan`, runs all tasks in group order with
intra-group async parallelism, fires TUI callbacks, and returns a populated `ContextDict`.

### Context injection

Before executing a task, all `{placeholder}` variables in `system_prompt_template` are
replaced with values from the current context dict:

```python
def fill_template(template: str, context: ContextDict) -> str:
    result = template
    for key, value in context.items():
        result = result.replace(f"{{{key}}}", value)
    return result
```

### Single task execution with retry

```python
async def execute_task(
    task: MicroTask,
    context: ContextDict,
    on_start: Callable,
    on_done: Callable,
    on_failed: Callable,
) -> None:
    task.status = TaskStatus.RUNNING
    on_start(task)

    for attempt in range(MAX_RETRIES):
        try:
            filled_prompt = fill_template(task.system_prompt_template, context)
            raw = await call_local_async(
                system_prompt=filled_prompt,
                input_text=task.input_text,
                anchor_str=task.anchor.value,
            )
            extracted = extract_after_anchor(raw, task.anchor)
            is_valid, cleaned = validate(extracted, task.anchor)
            if is_valid:
                context[task.output_key] = cleaned
                task.output = cleaned
                task.status = TaskStatus.DONE
                on_done(task)
                return
            task.retries += 1
        except Exception as e:
            task.retries += 1
            task.error = str(e)

    task.status = TaskStatus.FAILED
    if not task.error:
        task.error = f"Output failed validation after {MAX_RETRIES} attempts"
    on_failed(task)
```

### Full executor with parallel groups

```python
async def execute_plan(
    plan: TaskPlan,
    on_task_start: Callable[[MicroTask], None],
    on_task_done: Callable[[MicroTask], None],
    on_task_failed: Callable[[MicroTask], None],
) -> ContextDict:
    context: ContextDict = {}
    groups = build_execution_groups(plan.tasks)
    task_map = {t.id: t for t in plan.tasks}
    failed_ids: set[str] = set()

    for group in groups:
        # Mark tasks whose dependencies failed as SKIPPED before running
        runnable = []
        for task in group:
            if any(dep in failed_ids for dep in task.depends_on):
                task.status = TaskStatus.SKIPPED
                on_task_failed(task)
                failed_ids.add(task.id)
            else:
                runnable.append(task)

        if runnable:
            # Semaphore limits concurrent Ollama calls
            sem = asyncio.Semaphore(MAX_PARALLEL)
            async def run_with_sem(t):
                async with sem:
                    await execute_task(t, context, on_task_start, on_task_done, on_task_failed)

            await asyncio.gather(*[run_with_sem(t) for t in runnable])

        # Collect newly failed tasks for the next group's skip check
        for task in group:
            if task.status == TaskStatus.FAILED:
                failed_ids.add(task.id)

    return context
```

---

## 11. Stage 3 — Assembler (`adp/stages/assembler.py`)

### What it does

Sends the relevant parts of the context dict to Claude with an assembly prompt. Claude returns
a JSON object `{"files": {"filename.ext": "complete content"}}`. The assembler parses this
and returns `dict[str, str]`.

### The hardcoded assembly system prompt

```
You are a file assembler. You receive named code or text fragments that are parts of a
software project or document. Assemble them into complete, coherent, production-ready files.

RULES:
1. Return ONLY a JSON object. No prose. No explanation. No markdown fences.
2. The JSON must match exactly: {"files": {"filename.ext": "complete file content"}}
3. File content must be complete and valid — not truncated, not ellipsis-shortened.
4. Combine code fragments in correct order: imports, then types, then logic, then entry point.
5. Use ONLY content from the provided fragments. Do not invent additional logic.
6. If a fragment value is "[MISSING]", add a comment in the file noting it is missing
   and continue assembling the rest.

Fragments:
{fragments_json}

JSON:
```

### Implementation

```python
import json
import re
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from adp.models.task import TaskPlan, ContextDict
from adp.config import CLOUD_MODEL, ANTHROPIC_API_KEY

ASSEMBLER_SYSTEM_PROMPT = """...(exact prompt above)..."""


def assemble(plan: TaskPlan, context: ContextDict) -> dict[str, str]:
    # Build fragments dict — mark missing keys explicitly
    fragments = {}
    for key in plan.final_output_keys:
        fragments[key] = context.get(key, "[MISSING]")

    fragments_json = json.dumps(fragments, indent=2)
    prompt = ASSEMBLER_SYSTEM_PROMPT.replace("{fragments_json}", fragments_json)

    llm = ChatAnthropic(
        model=CLOUD_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0.0,         # deterministic assembly
        max_tokens=16384,        # assembler may produce large files
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    raw = response.content
    clean = re.sub(r"```json\s*|\s*```", "", raw).strip()
    data = json.loads(clean)
    return data["files"]
```

---

## 12. Writer (`adp/writer.py`)

```python
from pathlib import Path


def write_output_files(
    files: dict[str, str],
    output_dir: str,
) -> list[tuple[str, int]]:
    """
    Write all files to output_dir. Create directory tree as needed.
    Returns list of (filename, byte_count) for TUI display.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, content in files.items():
        path = base / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        size = path.stat().st_size
        if size == 0:
            raise IOError(f"File {filename} was written but is 0 bytes")
        written.append((filename, size))
    return written
```

---

## 13. TUI Architecture (`adp/tui/`)

### Design Goal

The TUI must feel like Claude Code or Codex CLI. It is a terminal-first experience. There is
no web UI. The user interacts entirely through the terminal.

### Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  ⬡ ADP  Agentic Decomposition Pipeline        cloud: claude-sonnet  │
│         local: qwen2.5-coder:7b                 ● Ollama connected  │
├──────────────────────────────────────────────────────────────────────┤
│ TASK PLAN (9 tasks)           │ CURRENT TASK                        │
│                               │                                      │
│  ✓ t1  resolve data model     │  ┌ System Prompt ─────────────────  │
│  ✓ t2  resolve py version     │  │ You are a FastAPI endpoint...    │
│  ✓ t3  resolve fastapi ver    │  │ EXAMPLES:                        │
│  ▶ t7  write POST /orders     │  │ Input: "class X..."              │
│  ▶ t8  write GET /orders      │  │ Code: @app.post(...)             │
│  ○ t9  write GET /orders/id   │  └──────────────────────────────── │
│  ○ t10 write PATCH /orders    │                                      │
│  ○ t11 write DELETE /orders   │  ┌ Output (streaming) ────────────  │
│  ○ t12 write pyproject.toml   │  │ @app.post("/orders", ...)        │
│                               │  │ def create_order(order: Order..  │
│  [t7, t8] running in parallel │  │ ▌                                │
│                               │  └──────────────────────────────── │
├──────────────────────────────────────────────────────────────────────┤
│ OUTPUT FILES: main.py  pyproject.toml                               │
├──────────────────────────────────────────────────────────────────────┤
│ [ctrl+c] cancel   [ctrl+l] clear   [↑↓] history   [enter] submit   │
└──────────────────────────────────────────────────────────────────────┘
  ❯ ▌
```

### Themes (`adp/tui/themes.py`)

Define ALL visual constants here. Never hardcode a color or symbol anywhere else.

```python
# Status icons
ICON_PENDING   = "○"
ICON_RUNNING   = "▶"
ICON_DONE      = "✓"
ICON_FAILED    = "✗"
ICON_SKIPPED   = "–"
ICON_PARALLEL  = "⟳"    # shown beside group label when multiple tasks run together

# Rich style strings
COLOR_HEADER   = "bold cyan"
COLOR_PENDING  = "dim white"
COLOR_RUNNING  = "bold yellow"
COLOR_DONE     = "bold green"
COLOR_FAILED   = "bold red"
COLOR_SKIPPED  = "dim red"
COLOR_ANCHOR   = "bold magenta"     # anchor word in prompt display
COLOR_INJECT   = "bold blue"        # injected {placeholder} sections
COLOR_EXAMPLE  = "dim cyan"         # few-shot example blocks
COLOR_STREAM   = "white"            # live model output
COLOR_BORDER   = "bright_black"
COLOR_FOOTER   = "dim white"
COLOR_CLOUD    = "bold blue"
COLOR_LOCAL    = "bold green"
COLOR_FILE     = "bold cyan"
COLOR_SIZE     = "dim white"

PANEL_BORDER   = "rounded"          # panel box style
APP_TITLE      = "⬡ ADP"
APP_SUBTITLE   = "Agentic Decomposition Pipeline"
```

### Panels (`adp/tui/panels.py`)

Each function returns a `rich.panel.Panel` or `rich.renderable`. The TUI controller calls
these to build the layout on each refresh.

```python
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.syntax import Syntax
from rich.console import Group as RichGroup

def render_header(cloud_model: str, local_model: str, ollama_ok: bool) -> Panel: ...
def render_task_list(tasks: list[MicroTask]) -> Panel: ...
def render_current_task(task: MicroTask | None, streamed_output: str) -> Panel: ...
def render_output_files(filenames: list[str]) -> Panel: ...
def render_footer() -> Text: ...
def render_completion_summary(
    written: list[tuple[str, int]],
    output_dir: str,
) -> Panel: ...
```

**render_current_task** must syntax-highlight the system prompt using `rich.syntax.Syntax`
with language `"text"` and highlight lines containing "EXAMPLES:", "{", and the anchor
word using different theme colors. The streamed output panel below it shows raw content
with a blinking cursor appended.

### TUI Controller (`adp/tui/app.py`)

The controller owns the `rich.live.Live` context and the `prompt_toolkit` `PromptSession`.

**Terminal ownership rule:**
`rich.live.Live` and `prompt_toolkit` cannot both own the terminal simultaneously. The
lifecycle is:

```
1. Start prompt_toolkit → collect user input → user presses Enter
2. Stop prompt_toolkit
3. Start rich.live.Live (refresh_per_second=10)
4. Run pipeline in a background thread via asyncio.run() in ThreadPoolExecutor
   → pipeline fires callbacks that update a shared render state dict
   → main thread's Live loop reads that dict on each refresh
5. Pipeline completes → stop Live
6. Print completion summary (non-live rich.print)
7. Go to step 1 for next prompt (or exit if user pressed ctrl+c)
```

**Render state** is a plain dict guarded by a `threading.Lock`:

```python
render_state = {
    "tasks": [],
    "current_task": None,
    "streamed_output": "",
    "stage": "IDLE",         # IDLE | DECOMPOSING | EXECUTING | ASSEMBLING | WRITING | DONE
    "written_files": [],
    "output_dir": "",
}
```

Callbacks from the pipeline thread acquire the lock, update the dict, and release it.
The Live loop reads the dict (with lock) and calls the panel renderers.

### Input Handler (`adp/tui/input_handler.py`)

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from adp.config import HISTORY_FILE


def get_user_prompt(output_dir_hint: str = "") -> str | None:
    """
    Display styled input prompt. Returns entered text or None on ctrl+c / ctrl+d.
    Arrow keys navigate history. Multiline with shift+enter.
    """
    session = PromptSession(
        history=FileHistory(HISTORY_FILE),
        style=Style.from_dict({
            "prompt": "bold cyan",
            "": "white",
        }),
        wrap_lines=True,
    )
    hint = f"  output → {output_dir_hint}\n" if output_dir_hint else ""
    try:
        return session.prompt(f"{hint}  ❯ ")
    except (KeyboardInterrupt, EOFError):
        return None
```

---

## 14. Main Entry Point (`adp/main.py`)

### CLI interface

```
Usage: adp [OPTIONS] [PROMPT]

  Agentic Decomposition Pipeline

Arguments:
  PROMPT    Task prompt (omit for interactive TUI mode)

Options:
  --output   -o  PATH   Output directory  [default: ./adp_output]
  --model    -m  TEXT   Override local Ollama model
  --no-tui              Plain text output (for scripting/CI)
  --debug               Print all system prompts and raw outputs
  --version             Show version
  --help                Show this message
```

### Full pipeline orchestration

```python
async def run_pipeline(
    user_prompt: str,
    output_dir: str,
    callbacks: TUICallbacks,
    debug: bool = False,
) -> PipelineResult:

    # Stage 1 — Decompose
    callbacks.on_stage("DECOMPOSING")
    plan = decompose(user_prompt)
    callbacks.on_plan_ready(plan)

    if debug:
        for t in plan.tasks:
            print(f"\n[{t.id}] {t.description}")
            print(t.system_prompt_template)

    # Stage 2 — Execute
    callbacks.on_stage("EXECUTING")
    context = await execute_plan(
        plan,
        on_task_start=callbacks.on_task_start,
        on_task_done=callbacks.on_task_done,
        on_task_failed=callbacks.on_task_failed,
    )

    # Stage 3 — Assemble
    callbacks.on_stage("ASSEMBLING")
    files = assemble(plan, context)

    # Stage 4 — Write
    callbacks.on_stage("WRITING")
    written = write_output_files(files, output_dir)
    callbacks.on_complete(written, output_dir)

    return PipelineResult(files=files, context=context, tasks=plan.tasks)
```

### TUICallbacks dataclass

```python
@dataclass
class TUICallbacks:
    on_stage:       Callable[[str], None]
    on_plan_ready:  Callable[[TaskPlan], None]
    on_task_start:  Callable[[MicroTask], None]
    on_task_done:   Callable[[MicroTask], None]
    on_task_failed: Callable[[MicroTask], None]
    on_complete:    Callable[[list[tuple[str, int]], str], None]
```

In `--no-tui` mode, all callbacks are simple `print()` calls. In TUI mode, they update
`render_state` and trigger a live refresh.

---

## 15. `pyproject.toml`

```toml
[project]
name = "adp"
version = "0.1.0"
description = "Agentic Decomposition Pipeline — cloud decomposes, local executes"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.25.0",
    "langchain>=0.2.0",
    "langchain-anthropic>=0.1.0",
    "langchain-community>=0.2.0",
    "rich>=13.7.0",
    "prompt_toolkit>=3.0.43",
    "pydantic>=2.6.0",
    "networkx>=3.3",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.14",
]

[project.scripts]
adp = "adp.main:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 16. `.env.example`

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
LOCAL_MODEL=qwen2.5-coder:7b
OLLAMA_URL=http://localhost:11434
```

---

## 17. Implementation Order

Implement in exactly this order. Each step is independently testable before proceeding.

**Step 1 — `adp/models/task.py`**
No external dependencies. Define all dataclasses and enums.
Test: `python -c "from adp.models.task import MicroTask, TaskStatus; print('ok')"`

**Step 2 — `adp/config.py`**
No external dependencies. Verify env vars load from `.env`.

**Step 3 — `adp/engine/graph.py`**
Depends only on `models/task.py`. Write unit tests with hardcoded task lists.
Verify topological sort works, cycle detection raises, invalid group assignments raise.

**Step 4 — `adp/engine/validator.py`**
No external dependencies. Write unit tests for all AnchorType variants:
valid input, invalid input, markdown-fenced input, empty input.

**Step 5 — `adp/engine/local_client.py`**
Requires Ollama running with the configured model pulled.
Test: call with a one-sentence prompt and print the response before wiring into executor.

**Step 6 — `adp/engine/cloud_client.py`**
Thin wrapper around LangChain ChatAnthropic.
Test: single message call, print response.

**Step 7 — `adp/stages/decomposer.py`**
Test with 2–3 example prompts. Print the resulting TaskPlan as formatted JSON.
Verify: every task has a non-empty system_prompt_template containing "EXAMPLES:".

**Step 8 — `adp/stages/executor.py`**
Test with a hardcoded 3-task plan (group 0: t1+t2 parallel, group 1: t3 depending on t1).
Verify context injection fills placeholders in t3's template before the model call.
Verify parallel group runs both t1 and t2 concurrently.

**Step 9 — `adp/stages/assembler.py`**
Test with a hardcoded context dict containing 3 code fragments.
Verify the returned dict has at least one key with non-empty file content.

**Step 10 — `adp/writer.py`**
Write 2 test files to `/tmp/adp_test/`, verify sizes > 0, clean up.

**Step 11 — `adp/tui/themes.py` + `adp/tui/panels.py`**
Pure rendering functions, no pipeline logic.
Test by calling each renderer with mock data and printing to terminal.

**Step 12 — `adp/tui/input_handler.py`**
Run interactively. Verify arrow key history navigation, ctrl+c returns None.

**Step 13 — `adp/tui/app.py`**
Wire panels into Live layout. Test with a fake pipeline that fires callbacks at 0.5s
intervals simulating task progress — verify TUI updates without errors.

**Step 14 — `adp/main.py`**
Wire all stages. Run end-to-end with a minimal prompt:
`"Write a Python function that adds two numbers and a docstring for it."`
Verify at least one `.py` file is written to the output directory.

---

## 18. Testing Strategy

### Unit tests (no API calls, no Ollama required)

```
tests/test_graph.py
  - test_topological_sort_basic
  - test_cycle_detection_raises
  - test_invalid_group_assignment_raises
  - test_downstream_ids_transitive
  - test_parallel_group_extraction

tests/test_validator.py
  - test_json_valid
  - test_json_invalid
  - test_json_with_fences
  - test_json_with_trailing_text
  - test_code_valid
  - test_code_with_fences
  - test_code_too_short
  - test_toml_valid
  - test_toml_invalid
  - test_output_nonempty
  - test_extract_after_anchor_present
  - test_extract_after_anchor_absent

tests/test_decomposer.py
  - test_parse_task_plan_valid_json
  - test_parse_task_plan_missing_field_raises
  - test_decompose_retries_on_invalid_json  (mock LLM)
  - test_decompose_raises_after_max_retries (mock LLM)

tests/test_executor.py
  - test_fill_template_replaces_placeholders
  - test_fill_template_no_placeholders
  - test_execute_plan_serial_dependency     (mock local client)
  - test_execute_plan_parallel_group        (mock local client, verify concurrency)
  - test_execute_plan_failed_task_skips_downstream (mock local client)
  - test_execute_plan_retry_on_invalid_output (mock local client returns bad output twice)
```

### Integration tests (requires Ollama)

```
tests/test_local_client_integration.py
  - test_call_local_async_returns_string
  - test_call_local_async_respects_temperature_zero (two identical calls, same output)
  - test_check_ollama_connection_true
```

### End-to-end test (requires Anthropic API key + Ollama)

```
tests/test_e2e.py
  - test_full_pipeline_simple_prompt:
      prompt: "Write a Python function that reverses a string and a pytest test for it."
      assert: output dir contains at least one .py file
      assert: each .py file parses with ast.parse() without SyntaxError
      assert: all task statuses are DONE or SKIPPED (no FAILED)
```

---

## 19. Common Failure Modes and Their Fixes

| Failure | Root Cause | Fix |
|---|---|---|
| Local model outputs text before anchor | Model ignores anchor instruction | Add `"Do NOT write anything before the anchor word {anchor}."` to every system_prompt_template |
| JSON from local model has trailing explanation | Model appends reasoning | Validator truncates at last `}` or `]` — already handled in `validator.py` |
| Placeholder `{key}` not replaced | `output_key` mismatch with placeholder name | Add startup check: scan all templates for `{...}` and verify each key exists as an `output_key` in the plan |
| Parallel group ordering violates dependencies | Decomposer assigned wrong group numbers | `graph.py` catches this at `build_execution_groups` time and raises before execution begins |
| Ollama timeout on long code generation | Task too complex for model | Increase `LOCAL_TIMEOUT` in config, or instruct decomposer to split large code tasks further |
| Assembler invents new code | Context dict had missing keys | All missing keys are pre-filled with `"[MISSING]"` before assembler call — assembler prompt handles this explicitly |
| `rich.live.Live` and `prompt_toolkit` conflict | Both try to own the terminal | Follow the strict lifecycle in `tui/app.py`: stop prompt_toolkit, then start Live. Never run both at the same time. |
| Decomposer returns tasks with no examples | Decomposer prompt drift | The decomposer system prompt states this is NON-NEGOTIABLE. Add an assertion in `_parse_task_plan` that checks `"EXAMPLES:"` appears in every `system_prompt_template`. |

---

## 20. Non-Negotiable Rules

Read these before writing any code. These rules must be enforced by the implementation,
not just documented.

1. **Temperature is always 0.0 for local model calls.** Hardcoded in `local_client.py`.
   Never accept it as a parameter from outside that module.

2. **Every system prompt template generated by the decomposer must contain the string
   "EXAMPLES:".** Enforce this in `_parse_task_plan` with an assertion. Raise
   `DecompositionError` if any task lacks examples.

3. **The executor never modifies `system_prompt_template`.** It only fills placeholders
   via `fill_template()`. The template is immutable after decomposition.

4. **The assembler does not generate new code or content.** It combines fragments.
   If the assembled output looks like the assembler invented logic not present in any
   fragment, the assembly system prompt needs to be made more restrictive.

5. **Failed tasks must never produce empty context entries.** The context dict must not
   contain a key with an empty string value from a failed task. Only DONE tasks write to
   the context dict.

6. **The TUI must never block the pipeline.** All TUI callbacks must be non-blocking. If
   a callback needs to do more than update the render state dict, use a thread-safe queue.

7. **The cloud model is called exactly twice per pipeline run.** Once in `decomposer.py`,
   once in `assembler.py`. No other module calls the cloud model. Verify this by
   searching for `ChatAnthropic` instantiation — it must appear in exactly two files.
