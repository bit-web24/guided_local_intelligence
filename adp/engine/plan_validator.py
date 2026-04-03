"""Strict task-plan validation for ADP."""
from __future__ import annotations

import re
from pathlib import Path

from adp.engine.graph import build_execution_groups
from adp.models.task import TaskPlan


_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MODEL_TYPES = {"coder", "general"}
_NON_CONTENT_KEY_RE = re.compile(
    r"(^|_)(status|path|filename|file_name|dirname|dir_name|directory|folder|created|creation|mkdir)($|_)"
)
_NON_CONTENT_DESC_RE = re.compile(
    r"\b(create|created|creating)\b.*\b(file|directory|folder)\b|\b(file|directory|folder)\b.*\b(create|created|creating)\b",
    re.IGNORECASE,
)


class PlanValidationError(ValueError):
    """Raised when a decomposed task plan violates structural guarantees."""


def _looks_like_non_content_final_output(task) -> bool:
    key = task.output_key.lower()
    description = task.description.lower()
    if _NON_CONTENT_KEY_RE.search(key):
        return True
    if _NON_CONTENT_DESC_RE.search(description):
        return True
    return False


def validate_task_plan(plan: TaskPlan) -> None:
    """Validate the structural integrity of a task plan before execution."""
    if not plan.tasks:
        raise PlanValidationError("Task plan must contain at least one task.")

    task_ids = [task.id for task in plan.tasks]
    duplicate_ids = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
    if duplicate_ids:
        raise PlanValidationError(f"Task ids must be unique. Duplicates: {duplicate_ids}")

    output_keys = [task.output_key for task in plan.tasks]
    duplicate_keys = sorted({key for key in output_keys if output_keys.count(key) > 1})
    if duplicate_keys:
        raise PlanValidationError(
            f"Task output keys must be unique. Duplicates: {duplicate_keys}"
        )

    duplicate_final_keys = sorted(
        {key for key in plan.final_output_keys if plan.final_output_keys.count(key) > 1}
    )
    if duplicate_final_keys:
        raise PlanValidationError(
            f"final_output_keys must not contain duplicates: {duplicate_final_keys}"
        )

    duplicate_filenames = sorted(
        {name for name in plan.output_filenames if plan.output_filenames.count(name) > 1}
    )
    if duplicate_filenames:
        raise PlanValidationError(
            f"output_filenames must not contain duplicates: {duplicate_filenames}"
        )

    invalid_filenames = sorted(
        name for name in plan.output_filenames
        if Path(name).is_absolute() or ".." in Path(name).parts
    )
    if invalid_filenames:
        raise PlanValidationError(
            "output_filenames must be relative paths within the output directory: "
            f"{invalid_filenames}"
        )

    task_map = {task.id: task for task in plan.tasks}
    for task in plan.tasks:
        if task.model_type not in _MODEL_TYPES:
            raise PlanValidationError(
                f"Task '{task.id}' has invalid model_type '{task.model_type}'."
            )
        if task.parallel_group < 0:
            raise PlanValidationError(
                f"Task '{task.id}' has negative parallel_group {task.parallel_group}."
            )
        if not _SNAKE_CASE_RE.match(task.output_key):
            raise PlanValidationError(
                f"Task '{task.id}' output_key '{task.output_key}' must be snake_case."
            )
        if task.id in task.depends_on:
            raise PlanValidationError(f"Task '{task.id}' cannot depend on itself.")

        last_line = task.system_prompt_template.rstrip().splitlines()[-1].strip()
        if last_line != task.anchor.value:
            raise PlanValidationError(
                f"Task '{task.id}' template must end with '{task.anchor.value}', "
                f"got '{last_line}'."
            )

        placeholders = set(_PLACEHOLDER_RE.findall(task.system_prompt_template))
        expected_dep_keys = set()
        for dep_id in task.depends_on:
            dep_task = task_map.get(dep_id)
            if dep_task is not None:
                expected_dep_keys.add(dep_task.output_key)

        expected_tool_keys = {f"{task.id}_{tool_name}_result" for tool_name in task.mcp_tools}
        allowed_placeholders = {"input_text"} | expected_dep_keys | expected_tool_keys
        unknown_placeholders = sorted(placeholders - allowed_placeholders)
        if unknown_placeholders:
            raise PlanValidationError(
                f"Task '{task.id}' references unknown placeholders: {unknown_placeholders}"
            )

        missing_dep_placeholders = sorted(expected_dep_keys - placeholders)
        if missing_dep_placeholders:
            raise PlanValidationError(
                f"Task '{task.id}' depends on outputs not referenced in its template: "
                f"{missing_dep_placeholders}"
            )

        missing_tool_placeholders = sorted(expected_tool_keys - placeholders)
        if missing_tool_placeholders:
            raise PlanValidationError(
                f"Task '{task.id}' assigns MCP tools but does not reference their results: "
                f"{missing_tool_placeholders}"
            )

    unknown_final_keys = sorted(set(plan.final_output_keys) - set(output_keys))
    if unknown_final_keys:
        raise PlanValidationError(
            f"final_output_keys reference unknown task outputs: {unknown_final_keys}"
        )

    if plan.write_to_file:
        if not plan.output_filenames:
            raise PlanValidationError(
                "write_to_file=True requires at least one output filename."
            )
        non_content_final_outputs = sorted(
            task.output_key
            for task in plan.tasks
            if task.output_key in plan.final_output_keys
            and _looks_like_non_content_final_output(task)
        )
        if non_content_final_outputs:
            raise PlanValidationError(
                "write_to_file=True requires final_output_keys to be file-content fragments, "
                f"not file/directory status or path artifacts: {non_content_final_outputs}"
            )
    elif plan.output_filenames:
        raise PlanValidationError(
            "write_to_file=False requires output_filenames to be empty."
        )

    try:
        build_execution_groups(plan.tasks)
    except ValueError as exc:
        raise PlanValidationError(str(exc)) from exc
