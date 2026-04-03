"""Stage 2 — Executor.

Runs all micro-tasks in dependency order, with parallel execution within
each group. Injects upstream outputs into system prompt templates before
calling the small Ollama model.

Context injection is the entire mechanism:
    fill_template(task.system_prompt_template, context)
replaces every {placeholder} with the string value from context dict.
The local model never sees the original user prompt.

MCP integration (when enabled):
    MCP tool calls happen in execute_plan() — in the MAIN pipeline task —
    BEFORE asyncio.gather() spawns child tasks for local model calls.
    This is mandatory: anyio cancel scopes (used internally by stdio_client)
    must be entered and exited in the same asyncio Task. Calling call_tool()
    from inside asyncio.gather() child tasks crosses task boundaries and
    triggers "Attempted to exit cancel scope in a different task" errors.

    Flow per group:
        1. _prefetch_mcp_for_group()  ← main task, sequential, fills context
        2. asyncio.gather(...)         ← child tasks, local model calls only
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from adp.config import (
    get_model_config, MAX_PARALLEL, MAX_RETRIES,
    RETRY_INJECT_ERROR, RETRY_TEMPERATURE_STEP,
)
from adp.engine.graph import build_execution_groups
from adp.engine.local_client import call_local_async
from adp.engine.validator import extract_after_anchor, validate
from adp.models.task import ContextDict, MicroTask, TaskPlan, TaskStatus

logger = logging.getLogger(__name__)


def fill_template(template: str, context: ContextDict) -> str:
    """
    Replace all {placeholder} variables in the template with values from context.
    The template itself is never modified — only the filled copy is used.
    """
    result = template
    for key, value in context.items():
        result = result.replace(f"{{{key}}}", value)
    return result


# ---------------------------------------------------------------------------
# MCP pre-fetch — runs in the MAIN task, before asyncio.gather()
# ---------------------------------------------------------------------------

async def _prefetch_mcp_for_group(
    tasks: list[MicroTask],
    context: ContextDict,
    mcp_manager: Any,
    tool_registry: Any,
    on_tool_start: Callable[[MicroTask, str], None] | None = None,
    on_tool_done: Callable[[MicroTask, str, bool, str | None], None] | None = None,
) -> None:
    """
    For each task in the group that has mcp_tools assigned, resolve args
    and call the MCP server.

    Context key format: "{task.id}_{tool_name}_result"
    e.g. task t2 using read_text_file → writes "t2_read_text_file_result"

    Task-scoped keys are mandatory: if t2 reads pyproject.toml and t3 reads
    main.py, both using read_text_file, they must have DIFFERENT context keys.
    A shared tool name key (the old design) caused the second task to receive
    the first task's file content.

    The Decomposer is instructed to use "{task_id}_{tool_name}_result" placeholders
    in system_prompt_templates, e.g. "{t2_read_text_file_result}".

    MUST be called from the main pipeline task (never from inside gather).
    anyio cancel scopes in stdio_client are task-local and raise if called
    from a different asyncio.Task.
    """
    try:
        from adp.mcp.resolver import resolve_tool_args
    except ImportError:
        return   # mcp sub-package not available — silently skip

    for task in tasks:
        if not task.mcp_tools:
            continue
        for tool_name in task.mcp_tools:
            # Task-scoped key — unique per (task, tool) pair
            context_key = f"{task.id}_{tool_name}_result"
            if tool_name not in tool_registry:
                if on_tool_start is not None:
                    on_tool_start(task, tool_name)
                logger.warning(
                    f"Task '{task.id}' references unknown MCP tool '{tool_name}'. "
                    "Skipping."
                )
                context[context_key] = f"[MCP tool '{tool_name}' not found]"
                if on_tool_done is not None:
                    on_tool_done(task, tool_name, False, "not found")
                continue
            try:
                if on_tool_start is not None:
                    on_tool_start(task, tool_name)
                mcp_tool = tool_registry[tool_name]
                args = resolve_tool_args(mcp_tool, task, context)
                result = await mcp_manager.call_tool(tool_name, args)
                context[context_key] = result
                if on_tool_done is not None:
                    on_tool_done(task, tool_name, True, None)
                logger.debug(
                    f"MCP pre-fetch '{tool_name}' ({task.id}) → '{context_key}' "
                    f"({len(result)} chars)"
                )
            except Exception as e:
                logger.warning(
                    f"MCP tool '{tool_name}' for task '{task.id}' failed: {e}. "
                    "Injecting error notice."
                )
                context[context_key] = f"[MCP tool '{tool_name}' failed: {e}]"
                if on_tool_done is not None:
                    on_tool_done(task, tool_name, False, str(e))


# ---------------------------------------------------------------------------
# Single task executor — local model only, no MCP calls here
# ---------------------------------------------------------------------------

async def execute_task(
    task: MicroTask,
    context: ContextDict,
    on_start: Callable[[MicroTask], None],
    on_done: Callable[[MicroTask], None],
    on_failed: Callable[[MicroTask], None],
) -> None:
    """
    Execute a single micro-task with retry logic (local model only).

    MCP tool results must already be present in context before this is
    called. They are injected by _prefetch_mcp_for_group() which runs in
    the main pipeline task before asyncio.gather() starts.

    Retry strategy:
        - Attempt 0: temperature 0.0 (deterministic, standard behaviour)
        - Attempt N: temperature N * RETRY_TEMPERATURE_STEP (e.g. 0.1, 0.2)
          This breaks out of deterministic failure loops where the same prompt
          produces the same bad output.
        - On retry, if RETRY_INJECT_ERROR is True, the validation failure
          reason is appended to the input text so the model gets concrete
          feedback about what went wrong. The system_prompt_template is
          NEVER modified (immutable after decomposition).

    After MAX_RETRIES failures: mark FAILED (nothing written to context).
    """
    task.status = TaskStatus.RUNNING
    on_start(task)

    models = get_model_config()
    model_name = models.local_coder if task.model_type == "coder" else models.local_general
    last_validation_error: str | None = None

    for attempt in range(MAX_RETRIES):
        try:
            filled_prompt = fill_template(task.system_prompt_template, context)

            # Build input text — optionally inject previous failure reason
            effective_input = task.input_text
            if attempt > 0 and RETRY_INJECT_ERROR and last_validation_error:
                effective_input = (
                    f"{task.input_text}\n\n"
                    f"[RETRY — your previous output was rejected: "
                    f"{last_validation_error}. Fix the issue.]"
                )

            # Temperature escalation: 0.0 on first attempt, then step up
            temp_override: float | None = None
            if attempt > 0:
                temp_override = attempt * RETRY_TEMPERATURE_STEP

            raw = await call_local_async(
                system_prompt=filled_prompt,
                input_text=effective_input,
                anchor_str=task.anchor.value,
                model_name=model_name,
                temperature_override=temp_override,
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
            # Record why validation failed for the next retry's error injection
            last_validation_error = f"format validation failed for {task.anchor.value} output"
            task.retries += 1
        except Exception as e:
            task.retries += 1
            task.error = str(e)
            last_validation_error = str(e)

    task.status = TaskStatus.FAILED
    if not task.error:
        task.error = f"Output failed validation after {MAX_RETRIES} attempts"
    on_failed(task)


# ---------------------------------------------------------------------------
# Plan executor — orchestrates groups, MCP pre-fetch, and parallel execution
# ---------------------------------------------------------------------------

async def execute_plan(
    plan: TaskPlan,
    on_task_start: Callable[[MicroTask], None],
    on_task_done: Callable[[MicroTask], None],
    on_task_failed: Callable[[MicroTask], None],
    on_tool_start: Callable[[MicroTask, str], None] | None = None,
    on_tool_done: Callable[[MicroTask, str, bool, str | None], None] | None = None,
    mcp_manager: Any | None = None,
    tool_registry: Any | None = None,
    initial_context: ContextDict | None = None,
    on_group_complete: Callable[[TaskPlan, ContextDict], None] | None = None,
) -> ContextDict:
    """
    Execute all tasks in the plan in dependency order.

    For each group:
      1. _prefetch_mcp_for_group() — main task, sequential MCP calls
      2. asyncio.gather()          — child tasks, local model calls only

    This separation is mandatory: anyio cancel scopes (created internally by
    mcp's stdio_client) are task-local and cannot be crossed by gather tasks.

    Tasks whose dependencies failed are marked SKIPPED without executing.
    """
    context: ContextDict = dict(initial_context or {})
    groups = build_execution_groups(plan.tasks)
    failed_ids: set[str] = set()

    for task in plan.tasks:
        if task.status == TaskStatus.DONE and task.output is not None:
            context.setdefault(task.output_key, task.output)
        elif task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.RUNNING):
            task.status = TaskStatus.PENDING
            task.error = None
            task.output = None
            task.retries = 0

    for group in groups:
        runnable: list[MicroTask] = []

        for task in group:
            if task.status == TaskStatus.DONE:
                continue
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
            # Phase 1: MCP pre-fetch — MUST run in the main task
            if mcp_manager is not None and tool_registry is not None:
                await _prefetch_mcp_for_group(
                    runnable,
                    context,
                    mcp_manager,
                    tool_registry,
                    on_tool_start=on_tool_start,
                    on_tool_done=on_tool_done,
                )

            # Phase 2: Local model calls — safe to parallelise with gather
            sem = asyncio.Semaphore(MAX_PARALLEL)

            async def run_with_sem(t: MicroTask) -> None:
                async with sem:
                    await execute_task(
                        t, context,
                        on_task_start, on_task_done, on_task_failed,
                    )

            await asyncio.gather(*[run_with_sem(t) for t in runnable])

        # Collect newly failed/skipped tasks for next group's dependency check
        for task in group:
            if task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED):
                failed_ids.add(task.id)

        if on_group_complete is not None:
            on_group_complete(plan, context)

    return context
