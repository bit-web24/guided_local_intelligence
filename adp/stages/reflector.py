"""Stage 2.5 — Reflector (per-task semantic validation).

Runs after execution completes, before assembly. For each DONE task, the
reflector asks a model whether the task's output correctly satisfies its
description — a binary PASS/FAIL check with a one-line reason.

Hybrid model routing:
    - Most reflections use the LOCAL model (pattern-matching validation).
      This is the >90% case: format compliance, basic structure, non-empty.
    - Complex code tasks with multiple upstream dependencies escalate to the
      CLOUD model for reasoning-heavy validation (logic correctness, coherence).

The routing heuristic is intentionally conservative: only Code-anchor tasks
whose description contains implementation verbs AND depend on >= N upstream
tasks are escalated. Everything else stays local.

Reflection is scoped: the model sees ONLY the task description and its
output, never the full plan or user prompt. This is the same principle that
makes local execution reliable — narrow scope + few-shot examples.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable

from adp.config import (
    get_model_config,
    MAX_PARALLEL,
    REFLECT_CLOUD_DEP_THRESHOLD,
)
from adp.engine.local_client import call_local_async
from adp.engine.cloud_client import call_cloud_async
from adp.models.task import (
    ContextDict,
    MicroTask,
    ReflectionResult,
    TaskPlan,
    TaskStatus,
    AnchorType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded reflection prompt — scoped, few-shot, binary output
# ---------------------------------------------------------------------------
REFLECTION_PROMPT = """\
You are an output validator. You receive a task description and the task's
actual output. Determine if the output correctly satisfies the task.

Rules:
1. Answer ONLY with "PASS" or "FAIL — <one-line reason>". Nothing else.
2. PASS means the output is a correct and complete response to the task.
3. FAIL means the output is wrong, incomplete, off-topic, or malformed.
4. Be strict: if the output is empty, obviously wrong, or does not match
   the expected format, it MUST fail.
5. Be practical: minor style differences are acceptable if the output is
   functionally correct.

EXAMPLES:
Task: "Write a Python function that adds two numbers"
Expected format: Code
Output:
def add(a, b):
    return a + b
Verdict: PASS

Task: "Write a Python function that adds two numbers"
Expected format: Code
Output:
Hello world
Verdict: FAIL — output is not a function that adds numbers

Task: "Extract the date from the text"
Expected format: JSON
Output:
{"date": "2026-03-21"}
Verdict: PASS

Task: "Extract the date from the text"
Expected format: JSON
Output:
{"name": "John"}
Verdict: FAIL — output is a name extraction, not a date extraction

Task: "Write the GET /health endpoint for app.py"
Expected format: Code
Output:
@app.get("/health")
def health():
    return {"status": "ok"}
Verdict: PASS

Task: "Write the GET /health endpoint for app.py"
Expected format: Code
Output:
from flask import Flask
app = Flask(__name__)
Verdict: FAIL — output is Flask app setup, not a health endpoint

---
Task: "{task_description}"
Expected format: {anchor_type}
Output:
{task_output}

Verdict:"""


# Implementation verbs that suggest a task requires reasoning to validate
_IMPL_VERBS = re.compile(
    r"\b(write|implement|generate|create|build|produce|code|develop)\b",
    re.IGNORECASE,
)


def should_use_cloud(task: MicroTask) -> bool:
    """Determine if a task's reflection should use the cloud model.

    Heuristic: Code-anchor tasks with implementation verbs in their
    description AND >= REFLECT_CLOUD_DEP_THRESHOLD upstream dependencies
    are escalated to the cloud model. Everything else stays local.

    This is intentionally conservative — >90% of reflections stay local.
    """
    if task.anchor != AnchorType.CODE:
        return False
    if len(task.depends_on) < REFLECT_CLOUD_DEP_THRESHOLD:
        return False
    return bool(_IMPL_VERBS.search(task.description))


def _build_reflection_prompt(task: MicroTask) -> str:
    """Build the filled reflection prompt for a single task.

    Uses str.replace() instead of .format() because the prompt template
    contains JSON examples with curly braces that .format() would interpret
    as format specifiers. Same approach as fill_template() in executor.py.
    """
    prompt = REFLECTION_PROMPT
    prompt = prompt.replace("{task_description}", task.description)
    prompt = prompt.replace("{anchor_type}", task.anchor.value.rstrip(":"))
    prompt = prompt.replace("{task_output}", task.output or "(empty)")
    return prompt


def _parse_verdict(raw: str) -> tuple[bool, str]:
    """Parse the model's verdict into (passed, reason).

    Expected formats:
        "PASS"
        "FAIL — reason text"
        "FAIL - reason text"
    """
    clean = raw.strip()
    if clean.upper().startswith("PASS"):
        return True, "PASS"
    # Extract reason after FAIL
    match = re.match(r"FAIL\s*[—\-–:]\s*(.*)", clean, re.IGNORECASE | re.DOTALL)
    if match:
        return False, match.group(1).strip() or "no reason given"
    if clean.upper().startswith("FAIL"):
        return False, "no reason given"
    # Ambiguous output — treat as fail
    return False, f"ambiguous verdict: {clean[:100]}"


async def reflect_task(
    task: MicroTask,
    use_cloud: bool = False,
) -> ReflectionResult:
    """Reflect on a single completed task.

    Args:
        task: the MicroTask to validate (must have status DONE and output set)
        use_cloud: if True, use the cloud model for reasoning-heavy validation

    Returns:
        ReflectionResult with pass/fail and reason
    """
    if task.status != TaskStatus.DONE or not task.output:
        return ReflectionResult(
            task_id=task.id,
            passed=False,
            reason="task has no output to reflect on",
            used_cloud=False,
        )

    prompt = _build_reflection_prompt(task)

    try:
        if use_cloud:
            raw = await call_cloud_async(
                system_prompt=prompt,
                user_message="Evaluate this output.",
                temperature=0.0,
                max_tokens=256,
                stage_name="reflector:cloud",
            )
        else:
            models = get_model_config()
            raw = await call_local_async(
                system_prompt=prompt,
                input_text="Evaluate this output.",
                anchor_str="Verdict:",
                model_name=models.local_general,
                temperature_override=0.0,
                stage_name="reflector:local",
            )
    except Exception as e:
        logger.warning(f"Reflection call failed for {task.id}: {e}")
        # On reflection failure, default to PASS — don't block the pipeline
        # because the reflection infrastructure failed
        return ReflectionResult(
            task_id=task.id,
            passed=True,
            reason=f"reflection call failed ({e}), defaulting to PASS",
            used_cloud=use_cloud,
        )

    # Extract after "Verdict:" anchor — the model may echo the anchor word
    verdict_idx = raw.rfind("Verdict:")
    if verdict_idx != -1:
        raw = raw[verdict_idx + len("Verdict:"):].strip()
    else:
        raw = raw.strip()

    passed, reason = _parse_verdict(raw)
    return ReflectionResult(
        task_id=task.id,
        passed=passed,
        reason=reason,
        used_cloud=use_cloud,
    )


async def reflect_plan(
    plan: TaskPlan,
    context: ContextDict,
    on_task_reflected: Callable[[MicroTask, ReflectionResult], None] | None = None,
) -> list[ReflectionResult]:
    """Reflect on all completed tasks in the plan.

    Runs reflections in parallel (bounded by MAX_PARALLEL semaphore).
    Tasks that are not DONE are skipped.

    Args:
        plan: the executed task plan
        context: the context dict (not modified by reflection)
        on_task_reflected: optional callback fired after each reflection

    Returns:
        list of ReflectionResults for all DONE tasks
    """
    done_tasks = [t for t in plan.tasks if t.status == TaskStatus.DONE]
    if not done_tasks:
        return []

    sem = asyncio.Semaphore(MAX_PARALLEL)
    results: list[ReflectionResult] = []

    async def _reflect_one(task: MicroTask) -> ReflectionResult:
        async with sem:
            use_cloud = should_use_cloud(task)
            result = await reflect_task(task, use_cloud=use_cloud)
            if on_task_reflected:
                on_task_reflected(task, result)
            return result

    results = await asyncio.gather(*[_reflect_one(t) for t in done_tasks])
    return list(results)


def has_reflection_failures(results: list[ReflectionResult]) -> bool:
    """Return True if any reflection result is a FAIL."""
    return any(not r.passed for r in results)


def reflection_failure_summary(results: list[ReflectionResult]) -> str:
    """Build a human-readable summary of reflection failures."""
    failures = [r for r in results if not r.passed]
    if not failures:
        return "All reflections passed."
    lines = [f"  {r.task_id}: FAIL — {r.reason}" for r in failures]
    return f"Reflection found {len(failures)} issue(s):\n" + "\n".join(lines)
