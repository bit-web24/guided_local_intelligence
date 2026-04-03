"""Stage 1 — Decomposer.

Sends the user prompt to the large Ollama model with a hardcoded system prompt
that instructs it to return a dependency-ordered JSON task plan.

The large model is called here exactly once per pipeline run (with up to 6
retries on JSON parse failure using self-correction messages).
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Callable

from adp.engine.cloud_client import call_cloud_with_history
from adp.engine.plan_validator import PlanValidationError, validate_task_plan
from adp.models.task import AnchorType, MicroTask, TaskPlan
from adp.config import CLOUD_TEMPERATURE, DECOMPOSITION_MAX_RETRIES

# Avoid a hard dependency on the mcp sub-package at import time
try:
    from adp.mcp.registry import ToolRegistry
except ImportError:
    ToolRegistry = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Hardcoded decomposition system prompt — never configurable.
# Changing this prompt changes pipeline behaviour for every user.
# ---------------------------------------------------------------------------
DECOMPOSER_SYSTEM_PROMPT = """\
You are a task decomposition engine. You receive a complex user request and break it into
the smallest possible atomic micro tasks that together produce the complete deliverable.

Your job is to PLAN for a small local model, not to solve the request yourself.
The cloud model must produce a path that makes local code generation easy:
- identify exact files
- identify exact symbols / sections to generate
- identify exact dependencies between those pieces
- keep each coding task small enough that a local coder model can complete it reliably

RULES:
1. EXTREME MICRO-GRANULARITY: Each task must have exactly ONE output — one entity,
   one code block, one decision, one file section. Break the goal down into the
   absolute smallest possible sequential tasks. A task must NEVER be broad
   (e.g., "Analyze everything" or "Write the whole file").
   - For code: Ask a small model to write only 1 or 2 small functions/classes per task.
   - For text: Do not ask a small model to synthesize too much information at once.
   - Aim for 5 to 15 micro-tasks for any non-trivial request.
   - One model call should answer ONE atomic question only.
   - NEVER create a task like "extract everything" or "analyze the whole request".
   - Prefer specialist tasks such as intent detection, single-entity extraction,
     single-value validation, tool selection, argument building, syntax checking,
     and targeted repair.

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
   to produce the final files (or final text).

9. For tasks with upstream dependencies, include the injected context BETWEEN the
   examples and the final input, using {placeholder} syntax matching the output_key
   of the dependency exactly.

10. For code-generation requests, the cloud model must DECOMPOSE before any code-writing task:
   - First create setup/contract/path tasks such as filenames, API shapes, schemas,
     function signatures, route lists, config fragments, or file skeleton sections.
   - Then create tiny coder tasks that implement only one small file section, one
     endpoint, one helper, one test, or one config block at a time using those
     upstream outputs as injected context.
   - Never create a single task that asks the local model to write an entire app,
     whole file, or multiple unrelated components at once.

11. Every coder task for source code must make the target edit location obvious.
   The prompt should tell the local model what file or section it is producing,
   such as "imports for app/main.py", "Pydantic model for models.py", or
   "GET /health endpoint body for app.py". Prefer section-level outputs that the
   assembler can combine into the final file.

12. Prefer plans where cloud outputs are guidance artifacts and local outputs are
   the actual code artifacts. The cloud model may define structure, but the local
   coder model should generate the implementation code whenever possible.

13. For user-understanding and tool-use requests, prefer specialist pipelines made
   of tiny classification and extraction tasks.
   GOOD specialist shape:
   - t1: detect intent label only
   - t2: extract one entity only (e.g. date)
   - t3: extract one entity only (e.g. destination)
   - t4: validate one extracted value only
   - t5: select one tool name only
   - t6: build exact JSON arguments only
   BAD shape:
   - t1: "extract intent, entities, tool, and arguments in one step"

14. For code-generation requests, use the SAME specialist principle but map it to
   coding artifacts rather than user-intent slots.
   GOOD specialist code shape:
   - detect project type or framework
   - define output directory or file map
   - define one contract or schema
   - define one route or one file skeleton
   - generate one code fragment
   - verify one fragment
   - repair one fragment if invalid
   BAD shape:
   - "write the backend"
   - "write the whole router"
   - "generate all CRUD endpoints in one task"

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
      "parallel_group": 0,
      "model_type": "coder"
    }
  ],
  "final_output_keys": ["key1", "key2"],
  "output_filenames": ["main.py", "pyproject.toml"],
  "write_to_file": true
}

MODEL SELECTION:
- Set `"model_type": "coder"` for tasks writing Python, JS, SQL, HTML, JSON, TOML, etc.
- Set `"model_type": "general"` for tasks writing prose, explanations, extracting entities, or markdown.
- For coding requests, prefer `"general"` for planning/contract tasks and `"coder"` for the
  tiny implementation tasks that consume those plans.

FILE OUTPUT RULES:
- If the user explicitly asks for files to be generated (e.g. "Create a FastAPI app"), set `"write_to_file": true` and provide `"output_filenames"`.
- If the user is just asking a conversational question, requesting an explanation, or summarizing text without needing files, set `"write_to_file": false` AND set `"output_filenames": []`.

CODE PLANNING RULES:
- Treat the cloud model as an architect and the local coder as the builder.
- Break code work into assembler-friendly fragments: imports, constants, schemas,
  one class, one endpoint, one helper function, one test case group, one config section.
- If a file is new, prefer separate tasks for skeleton/structure and for each meaningful code section.
- If a file already exists, prefer MCP-assisted tasks that read the file and then generate only the needed delta.
- The task description shown in the UI should mention the concrete artifact, not a broad goal.
  GOOD: "Write GET / endpoint for app.py"
  BAD:  "Write Flask application code"

EXAMPLE of a correct system_prompt_template for a task with NO upstream dependencies:

"You are a date extractor. Extract ONLY the date mentioned in the text.
Return ONLY a JSON object in this exact format: {\\"date\\": \\"YYYY-MM-DD\\"}
or {\\"date\\": null} if no date is present. Nothing else.

EXAMPLES:
Input: \\"I want to fly to Delhi on Friday March 21\\"
JSON: {\\"date\\": \\"2026-03-21\\"}

Input: \\"Book a table for tomorrow\\"
JSON: {\\"date\\": null}

Input: \\"Schedule the meeting for April 5th 2026\\"
JSON: {\\"date\\": \\"2026-04-05\\"}

Input: \\"Call me at 3pm\\"
JSON: {\\"date\\": null}

---
Input: {input_text}
JSON:"

EXAMPLE of a correct system_prompt_template for a task WITH upstream dependencies:

"You are a FastAPI endpoint writer. Write ONLY the Python function for one POST endpoint.
Use the exact schema and store code provided below. No imports. No explanation.

EXAMPLES:
Schema: class ItemCreate(BaseModel):\\n    name: str\\nStore: items = {}
Code: @app.post(\\"/items\\", status_code=201)\\ndef create_item(item: ItemCreate):\\n    id = str(uuid4())\\n    items[id] = item.dict()\\n    return {\\"id\\": id, **item.dict()}

Schema: class UserCreate(BaseModel):\\n    email: str\\nStore: users = {}
Code: @app.post(\\"/users\\", status_code=201)\\ndef create_user(user: UserCreate):\\n    id = str(uuid4())\\n    users[id] = user.dict()\\n    return {\\"id\\": id, **user.dict()}

---
Schema in use:
{schema_create}

Store in use:
{store_code}

Input: Write the POST endpoint for this resource.
Code:"

EXAMPLE of a good specialist decomposition for a tool-use request:
- t1: detect intent label only
- t2: extract date only
- t3: extract destination city only
- t4: validate destination city only
- t5: choose tool name only
- t6: build tool arguments JSON only
- t7: write a short final answer using {tool_args}

EXAMPLE of a good code decomposition shape:
- t1: produce absolute path or filename map
- t2: produce dependency/config fragment
- t3: produce file skeleton for app.py
- t4: produce request/response schema or route contract
- t5: write one endpoint using {file_skeleton} and {route_contract}
- t6: write one helper using {route_contract}
- t7: write one test file section using {route_contract} and {endpoint_code}

BAD decomposition for code:
- t1: "Write the whole Flask app"
- t2: "Write all tests"

GOOD decomposition for code:
- t1: "Define output files for Flask hello app"
- t2: "Write pyproject.toml for Flask app"
- t3: "Write app.py imports and Flask app initialization"
- t4: "Write GET / endpoint for app.py"
- t5: "Write app.py run block"
"""

# ---------------------------------------------------------------------------
# MCP tool-assignment block — appended to the Decomposer prompt when tools exist
# ---------------------------------------------------------------------------
_MCP_TOOL_BLOCK_TEMPLATE = """\

AVAILABLE MCP TOOLS:
{tool_summary}

MCP TOOL RULES (read carefully — mistakes here cause task failures):

1. CONTEXT KEY FORMAT: The tool result is written to context as:
     {{task_id}}_{{tool_name}}_result
   Example: task "t3" using "read_text_file" → {{t3_read_text_file_result}}
   You MUST use this exact key in the system_prompt_template placeholder.
   WRONG: {{read_text_file_result}}  ← shared across tasks, causes collisions
   RIGHT: {{t3_read_text_file_result}} ← scoped to task t3 only

2. ASSIGN TOOLS TO WORK TASKS, NOT TO SEPARATE READ TASKS:
   Do NOT create a task whose only purpose is to read a file and pass it through.
   Instead, assign the read tool directly to the task that USES the content.
   BAD:  t2=read_pyproject, t3=analyze_pyproject (depends on t2)
   GOOD: t2=analyze_and_fix_pyproject (assigned read_text_file, reads + fixes in one task)

3. FILE PATHS MUST BE ABSOLUTE:
   The MCP filesystem server root is: {project_dir}
   Use absolute paths: "{project_dir}/pyproject.toml", "{project_dir}/main.py"
   DO NOT use relative paths like "pyproject.toml" or "./main.py" — they will fail.

4. LIMIT TO 1-2 TOOLS PER TASK. Only assign tools where the file content would
   genuinely determine the model output (e.g., completing an existing file).
   For tasks generating new content from scratch, do not assign file-read tools.

JSON fields to add to the task when using MCP tools:
  "mcp_tools": ["read_text_file"],
  "mcp_tool_args": {{"read_text_file": {{"path": "{project_dir}/pyproject.toml"}}}}
"""


class DecompositionError(Exception):
    """Raised when the large model returns malformed JSON or a plan that fails validation."""
    pass


async def decompose(
    user_prompt: str,
    tool_registry=None,
    project_dir: str = "",
    on_retry: Callable[[int, str], None] | None = None,
) -> TaskPlan:
    """
    Send the user prompt to the large Ollama model and parse the returned
    JSON task plan into a TaskPlan object.

    tool_registry: if provided and non-empty, the tool list is injected into
    the system prompt so the Decomposer can assign MCP tools per task.

    project_dir: absolute path to the project directory. Injected into the
    MCP tool block so the Decomposer generates correct absolute file paths
    in mcp_tool_args instead of relative paths that fail the filesystem server.

    Retries up to DECOMPOSITION_MAX_RETRIES times using self-correction
    messages if JSON parse or plan validation fails.
    """
    # Build the effective system prompt (base + optional MCP tool block)
    system_prompt = DECOMPOSER_SYSTEM_PROMPT
    if tool_registry is not None and not tool_registry.is_empty():
        tool_summary = tool_registry.tool_summary_for_decomposer()
        system_prompt += _MCP_TOOL_BLOCK_TEMPLATE.format(
            tool_summary=tool_summary,
            project_dir=project_dir or "(unknown — use absolute paths)",
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_error: Exception | None = None
    for attempt in range(DECOMPOSITION_MAX_RETRIES):
        raw = await call_cloud_with_history(
            messages=messages,
            temperature=CLOUD_TEMPERATURE,
            max_tokens=8192,
        )
        # Strip any accidental markdown fences
        clean = re.sub(r"```json\s*|\s*```", "", raw).strip()
        try:
            data = json.loads(clean)
            return _parse_task_plan(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = e
            if on_retry is not None:
                on_retry(attempt + 1, str(e))
            # Self-correction: add the bad response + error to conversation
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": (
                    f"Your response failed to parse: {e}. "
                    "Return ONLY valid JSON matching the schema. No prose. No fences."
                ),
            })

    raise DecompositionError(
        f"Decomposition failed after {DECOMPOSITION_MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def decompose_sync(user_prompt: str) -> TaskPlan:
    """Synchronous wrapper — use only outside an event loop (e.g. scripts/tests)."""
    import asyncio
    return asyncio.run(decompose(user_prompt))


def _parse_task_plan(data: dict) -> TaskPlan:
    """
    Parse the raw JSON dict returned by the large model into a TaskPlan.

    Enforces non-negotiable rules:
    - Every task's system_prompt_template must contain "EXAMPLES:"
    - anchor must be a valid AnchorType value
    """
    tasks: list[MicroTask] = []
    for t in data["tasks"]:
        template = t["system_prompt_template"]
        if "EXAMPLES:" not in template:
            raise DecompositionError(
                f"Task '{t['id']}' system_prompt_template missing 'EXAMPLES:' section. "
                "This is non-negotiable — all templates must contain few-shot examples."
            )
        tasks.append(MicroTask(
            id=t["id"],
            description=t["description"],
            system_prompt_template=template,
            input_text=t["input_text"],
            output_key=t["output_key"],
            depends_on=t.get("depends_on", []),
            anchor=AnchorType(t["anchor"]),
            parallel_group=int(t["parallel_group"]),
            model_type=t.get("model_type", "coder"),
            mcp_tools=t.get("mcp_tools", []),
            mcp_tool_args=t.get("mcp_tool_args", {}),
        ))

    plan = TaskPlan(
        tasks=tasks,
        final_output_keys=data["final_output_keys"],
        output_filenames=data.get("output_filenames", []),
        write_to_file=data.get("write_to_file", True),
    )
    validate_task_plan(plan)
    return plan
