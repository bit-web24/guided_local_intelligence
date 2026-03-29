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

from adp.config import MAX_PARALLEL, MAX_REPAIR_ATTEMPTS, MAX_RETRIES
from adp.engine.cache import build_task_cache_key, load_cached_output, save_cached_output
from adp.engine.graph import build_execution_groups
from adp.engine.local_client import call_local_async
from adp.engine.router import resolve_model_name, resolve_num_predict
from adp.engine.validator import extract_after_anchor, validate_task_output
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


def _build_retry_prompt(base_prompt: str, validation_error: str, previous_output: str) -> str:
    return (
        f"{base_prompt}\n\n"
        "RETRY INSTRUCTIONS:\n"
        "Your previous output was invalid. Correct it without adding explanation.\n"
        f"Validation error: {validation_error}\n"
        "Previous invalid output:\n"
        f"{previous_output}\n"
    )


def _build_repair_prompt(task: MicroTask, base_prompt: str, validation_error: str) -> str:
    return (
        "You are a repair engine for local-model micro-tasks.\n"
        "Fix the invalid output so it satisfies the original task exactly.\n"
        "Do not explain the fix. Return only the corrected output.\n\n"
        f"Original task description: {task.description}\n"
        f"Required anchor: {task.anchor.value}\n"
        f"Validation error: {validation_error}\n\n"
        "Original task prompt:\n"
        f"{base_prompt}\n"
    )


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

    model_name = resolve_model_name(task)
    num_predict = resolve_num_predict(task)
    last_invalid_output = ""
    last_validation_error = ""
    base_prompt = fill_template(task.system_prompt_template, context)
    cache_key = build_task_cache_key(
        task,
        model_name=model_name,
        system_prompt=base_prompt,
        input_text=task.input_text,
    )
    cached = load_cached_output(cache_key)
    if cached is not None:
        cached_result = validate_task_output(task, cached)
        if cached_result.ok:
            context[task.output_key] = cached_result.cleaned_output
            task.output = cached_result.cleaned_output
            task.status = TaskStatus.DONE
            on_done(task)
            return

    for attempt in range(MAX_RETRIES):
        try:
            filled_prompt = base_prompt
            if attempt > 0 and last_validation_error:
                filled_prompt = _build_retry_prompt(
                    filled_prompt,
                    last_validation_error,
                    last_invalid_output,
                )
            raw = await call_local_async(
                system_prompt=filled_prompt,
                input_text=task.input_text,
                anchor_str=task.anchor.value,
                model_name=model_name,
                num_predict=num_predict,
            )
            extracted = extract_after_anchor(raw, task.anchor)
            result = validate_task_output(task, extracted)
            if result.ok:
                # Only DONE tasks write to context — failed tasks write nothing
                context[task.output_key] = result.cleaned_output
                task.output = result.cleaned_output
                save_cached_output(cache_key, result.cleaned_output)
                task.status = TaskStatus.DONE
                on_done(task)
                return
            last_invalid_output = extracted
            last_validation_error = result.reason
            task.retries += 1
        except Exception as e:
            task.retries += 1
            task.error = str(e)

    if last_validation_error:
        repaired = await _attempt_repair(
            task=task,
            context=context,
            last_invalid_output=last_invalid_output,
            validation_error=last_validation_error,
        )
        if repaired is not None:
            context[task.output_key] = repaired
            task.output = repaired
            save_cached_output(cache_key, repaired)
            task.status = TaskStatus.DONE
            on_done(task)
            return

    task.status = TaskStatus.FAILED
    if not task.error:
        task.error = (
            f"Output failed validation after {MAX_RETRIES} attempts. "
            f"Last validator error: {last_validation_error or 'unknown'}"
        )
    on_failed(task)


async def _attempt_repair(
    task: MicroTask,
    context: ContextDict,
    last_invalid_output: str,
    validation_error: str,
) -> str | None:
    base_prompt = fill_template(task.system_prompt_template, context)
    repair_prompt = _build_repair_prompt(task, base_prompt, validation_error)
    repair_input = (
        "Repair this invalid output.\n\n"
        "Invalid output:\n"
        f"{last_invalid_output}"
    )

    for _ in range(MAX_REPAIR_ATTEMPTS):
        raw = await call_local_async(
            system_prompt=repair_prompt,
            input_text=repair_input,
            anchor_str=task.anchor.value,
            model_name=resolve_model_name(task, repair=True),
            num_predict=resolve_num_predict(task),
        )
        extracted = extract_after_anchor(raw, task.anchor)
        result = validate_task_output(task, extracted)
        if result.ok:
            return result.cleaned_output

    return None


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
