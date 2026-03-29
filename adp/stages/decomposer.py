"""Stage 1 — Decomposer.

Sends the user prompt to the large Ollama model with a hardcoded system prompt
that instructs it to return a dependency-ordered JSON task plan.

The large model is called here exactly once per pipeline run (with up to 3
retries on JSON parse failure using self-correction messages).
"""
from __future__ import annotations

import asyncio
import json
import re

from adp.engine.cloud_client import call_cloud_with_history
from adp.models.task import AnchorType, MicroTask, TaskPlan
from adp.config import CLOUD_TEMPERATURE

# ---------------------------------------------------------------------------
# Hardcoded decomposition system prompt — never configurable.
# Changing this prompt changes pipeline behaviour for every user.
# ---------------------------------------------------------------------------
DECOMPOSER_SYSTEM_PROMPT = """\
You are a task decomposition engine. You receive a complex user request and break it into
the smallest possible atomic micro tasks that together produce the complete deliverable.

RULES:
1. EXTREME MICRO-GRANULARITY: Each task must have exactly ONE output — one entity,
   one code block, one decision, one file section. Break the goal down into the
   absolute smallest possible sequential tasks. A task must NEVER be broad
   (e.g., "Analyze everything" or "Write the whole file").
   - For code: Ask a small model to write only 1 or 2 small functions/classes per task.
   - For text: Do not ask a small model to synthesize too much information at once.
   - Aim for 5 to 15 micro-tasks for any non-trivial request.

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

FILE OUTPUT RULES:
- If the user explicitly asks for files to be generated (e.g. "Create a FastAPI app"), set `"write_to_file": true` and provide `"output_filenames"`.
- If the user is just asking a conversational question, requesting an explanation, or summarizing text without needing files, set `"write_to_file": false` AND set `"output_filenames": []`.

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
"""


class DecompositionError(Exception):
    """Raised when the large model returns malformed JSON or a plan that fails validation."""
    pass


async def decompose(user_prompt: str) -> TaskPlan:
    """
    Send the user prompt to the large Ollama model and parse the returned
    JSON task plan into a TaskPlan object.

    Retries up to 3 times using self-correction messages if JSON parse fails.
    """
    messages = [
        {"role": "system", "content": DECOMPOSER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    last_error: Exception | None = None
    for attempt in range(3):
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
        f"Decomposition failed after 3 attempts. Last error: {last_error}"
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
        ))

    return TaskPlan(
        tasks=tasks,
        final_output_keys=data["final_output_keys"],
        output_filenames=data.get("output_filenames", []),
        write_to_file=data.get("write_to_file", True),
    )
