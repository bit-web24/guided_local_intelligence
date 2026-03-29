"""Task-plan validation for reliable local execution."""
from __future__ import annotations

import re

from adp.config import MAX_TASK_PROMPT_CHARS
from adp.models.task import MicroTask, TaskKind, TaskPlan


class PlanValidationError(ValueError):
    """Raised when a task plan is internally inconsistent."""


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_VALID_MODEL_TYPES = {"coder", "general"}


def _placeholders(template: str) -> set[str]:
    return {value for value in _PLACEHOLDER_RE.findall(template) if value != "input_text"}


def validate_task_plan(plan: TaskPlan) -> TaskPlan:
    """Validate internal plan consistency before execution."""
    task_ids = [task.id for task in plan.tasks]
    output_keys = [task.output_key for task in plan.tasks]

    if len(task_ids) != len(set(task_ids)):
        raise PlanValidationError("Task ids must be unique.")

    if len(output_keys) != len(set(output_keys)):
        raise PlanValidationError("Task output_key values must be unique.")

    id_to_task = {task.id: task for task in plan.tasks}
    key_to_task = {task.output_key: task for task in plan.tasks}

    for key in plan.final_output_keys:
        if key not in key_to_task:
            raise PlanValidationError(
                f"final_output_key '{key}' does not match any task output_key."
            )

    for task in plan.tasks:
        _validate_single_task(task, id_to_task, key_to_task)

    return plan


def _validate_single_task(
    task: MicroTask,
    id_to_task: dict[str, MicroTask],
    key_to_task: dict[str, MicroTask],
) -> None:
    if task.model_type not in _VALID_MODEL_TYPES:
        raise PlanValidationError(
            f"Task '{task.id}' uses invalid model_type '{task.model_type}'."
        )

    if not isinstance(task.task_kind, TaskKind):
        raise PlanValidationError(f"Task '{task.id}' has invalid task_kind '{task.task_kind}'.")

    if not task.system_prompt_template.rstrip().endswith(task.anchor.value):
        raise PlanValidationError(
            f"Task '{task.id}' system_prompt_template must end with '{task.anchor.value}'."
        )

    if len(task.system_prompt_template) > MAX_TASK_PROMPT_CHARS:
        raise PlanValidationError(
            f"Task '{task.id}' system prompt exceeds {MAX_TASK_PROMPT_CHARS} characters."
        )

    placeholders = _placeholders(task.system_prompt_template)
    dep_keys = {
        id_to_task[dep_id].output_key
        for dep_id in task.depends_on
        if dep_id in id_to_task
    }

    for dep_id in task.depends_on:
        if dep_id not in id_to_task:
            raise PlanValidationError(
                f"Task '{task.id}' depends on unknown task id '{dep_id}'."
            )

    unknown = sorted(placeholders - set(key_to_task))
    if unknown:
        raise PlanValidationError(
            f"Task '{task.id}' references unknown placeholders: {unknown}."
        )

    undeclared = sorted(placeholders - dep_keys)
    if undeclared:
        raise PlanValidationError(
            f"Task '{task.id}' references placeholders without matching dependencies: {undeclared}."
        )

    if task.max_output_chars is not None and task.max_output_chars <= 0:
        raise PlanValidationError(
            f"Task '{task.id}' max_output_chars must be positive when provided."
        )
