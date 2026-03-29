"""Stage 2 — Executor.

Runs all micro-tasks in dependency order, with parallel execution within
each group. Injects upstream outputs into system prompt templates before
calling the small Ollama model.

Context injection is the entire mechanism:
    fill_template(task.system_prompt_template, context)
replaces every {placeholder} with the string value from context dict.
The local model never sees the original user prompt.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from adp.config import LOCAL_CODER_MODEL, LOCAL_GENERAL_MODEL, MAX_PARALLEL, MAX_RETRIES
from adp.engine.graph import build_execution_groups
from adp.engine.local_client import call_local_async
from adp.engine.validator import extract_after_anchor, validate
from adp.models.task import ContextDict, MicroTask, TaskPlan, TaskStatus


def fill_template(template: str, context: ContextDict) -> str:
    """
    Replace all {placeholder} variables in the template with values from context.
    The template itself is never modified — only the filled copy is used.
    """
    result = template
    for key, value in context.items():
        result = result.replace(f"{{{key}}}", value)
    return result


async def execute_task(
    task: MicroTask,
    context: ContextDict,
    on_start: Callable[[MicroTask], None],
    on_done: Callable[[MicroTask], None],
    on_failed: Callable[[MicroTask], None],
) -> None:
    """
    Execute a single micro-task with retry logic.

    On each attempt:
    1. Fill placeholders in system_prompt_template with current context
    2. Call small Ollama model
    3. Extract content after anchor word
    4. Validate output by anchor type
    5. On success: write to context dict + mark DONE
    6. On failure: increment retries, try again

    After MAX_RETRIES failures: mark FAILED (nothing written to context).
    """
    task.status = TaskStatus.RUNNING
    on_start(task)

    model_name = LOCAL_CODER_MODEL if task.model_type == "coder" else LOCAL_GENERAL_MODEL

    for attempt in range(MAX_RETRIES):
        try:
            filled_prompt = fill_template(task.system_prompt_template, context)
            raw = await call_local_async(
                system_prompt=filled_prompt,
                input_text=task.input_text,
                anchor_str=task.anchor.value,
                model_name=model_name,
            )
            extracted = extract_after_anchor(raw, task.anchor)
            is_valid, cleaned = validate(extracted, task.anchor)
            if is_valid:
                # Only DONE tasks write to context — failed tasks write nothing
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


async def execute_plan(
    plan: TaskPlan,
    on_task_start: Callable[[MicroTask], None],
    on_task_done: Callable[[MicroTask], None],
    on_task_failed: Callable[[MicroTask], None],
) -> ContextDict:
    """
    Execute all tasks in the plan in dependency order.

    Groups are processed sequentially. Tasks within a group run concurrently
    up to MAX_PARALLEL concurrent Ollama calls (semaphore-limited).

    Tasks whose dependencies failed are marked SKIPPED without executing.
    """
    context: ContextDict = {}
    groups = build_execution_groups(plan.tasks)
    failed_ids: set[str] = set()

    for group in groups:
        runnable: list[MicroTask] = []

        for task in group:
            # Skip tasks whose dependencies have failed
            if any(dep in failed_ids for dep in task.depends_on):
                task.status = TaskStatus.SKIPPED
                task.error = (
                    f"Skipped because dependency "
                    f"{[d for d in task.depends_on if d in failed_ids]} failed"
                )
                on_task_failed(task)
                failed_ids.add(task.id)
            else:
                runnable.append(task)

        if runnable:
            sem = asyncio.Semaphore(MAX_PARALLEL)

            async def run_with_sem(t: MicroTask) -> None:
                async with sem:
                    await execute_task(
                        t, context, on_task_start, on_task_done, on_task_failed
                    )

            await asyncio.gather(*[run_with_sem(t) for t in runnable])

        # Collect newly failed/skipped tasks for next group's dependency check
        for task in group:
            if task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED):
                failed_ids.add(task.id)

    return context
