"""Stage for replanning a failed run using prior execution context."""
from __future__ import annotations

from adp.models.task import ContextDict, MicroTask, TaskPlan, TaskStatus
from adp.stages.decomposer import decompose


def _summarize_completed_outputs(plan: TaskPlan) -> str:
    completed = [
        f"- {task.id} → {task.output_key}: {task.description}"
        for task in plan.tasks
        if task.status == TaskStatus.DONE and task.output
    ]
    return "\n".join(completed) if completed else "- None"


def _summarize_failures(plan: TaskPlan) -> str:
    failures = [
        f"- {task.id} ({task.status.value}): {task.error or task.description}"
        for task in plan.tasks
        if task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED)
    ]
    return "\n".join(failures) if failures else "- None"


def get_completed_tasks(plan: TaskPlan) -> list[MicroTask]:
    """Return completed tasks that can be preserved across replans."""
    return [task for task in plan.tasks if task.status == TaskStatus.DONE and task.output]


def build_preserved_context(plan: TaskPlan, context: ContextDict) -> ContextDict:
    """Keep completed outputs and their task-scoped tool results."""
    completed_ids = {task.id for task in get_completed_tasks(plan)}
    completed_output_keys = {
        task.output_key
        for task in get_completed_tasks(plan)
    }
    return {
        key: value
        for key, value in context.items()
        if key in completed_output_keys
        or (
            key.endswith("_result")
            and any(key.startswith(f"{task_id}_") for task_id in completed_ids)
        )
    }


def _remaining_final_output_keys(plan: TaskPlan) -> list[str]:
    completed_output_keys = {task.output_key for task in get_completed_tasks(plan)}
    return [key for key in plan.final_output_keys if key not in completed_output_keys]


async def replan(
    user_prompt: str,
    previous_plan: TaskPlan,
    tool_registry=None,
    project_dir: str = "",
    on_retry=None,
) -> TaskPlan:
    """
    Request a fresh plan using the prior execution results and failure causes.

    The current implementation replans the full run, but it includes concise
    structured memory from the previous attempt so the new plan can avoid
    repeating the same failure mode.
    """
    completed_tasks = get_completed_tasks(previous_plan)
    if not completed_tasks:
        replan_prompt = (
            f"{user_prompt}\n\n"
            "Previous attempt failed. Generate a corrected plan from scratch while "
            "preserving any valid outputs conceptually when useful.\n\n"
            "Completed outputs from the prior attempt:\n"
            f"{_summarize_completed_outputs(previous_plan)}\n\n"
            "Failures to avoid:\n"
            f"{_summarize_failures(previous_plan)}\n"
        )
        return await decompose(
            replan_prompt,
            tool_registry=tool_registry,
            project_dir=project_dir,
            on_retry=on_retry,
        )

    remaining_final_keys = _remaining_final_output_keys(previous_plan)
    preserved_task_ids = ", ".join(task.id for task in completed_tasks)
    replan_prompt = (
        f"{user_prompt}\n\n"
        "Previous attempt failed. Generate ONLY the remaining corrective micro-tasks "
        "needed from the failure point onward. Do NOT recreate completed tasks.\n\n"
        "Completed tasks that remain in the plan unchanged:\n"
        f"{_summarize_completed_outputs(previous_plan)}\n\n"
        "You may depend on those completed tasks using their exact existing task ids "
        f"({preserved_task_ids}) and reference their output_key placeholders in new templates.\n"
        "Return ONLY NEW tasks for unfinished or corrective work.\n"
        "Do not recreate already completed outputs.\n"
        "Use very small local-model-friendly micro-tasks.\n\n"
        "Final outputs still needing new or corrected coverage:\n"
        f"{'- ' + ', '.join(remaining_final_keys) if remaining_final_keys else '- corrective outputs only'}\n\n"
        "Failures to avoid:\n"
        f"{_summarize_failures(previous_plan)}\n"
    )
    return await decompose(
        replan_prompt,
        tool_registry=tool_registry,
        project_dir=project_dir,
        on_retry=on_retry,
        existing_tasks=completed_tasks,
        final_output_keys_override=previous_plan.final_output_keys,
        output_filenames_override=previous_plan.output_filenames,
        write_to_file_override=previous_plan.write_to_file,
    )
