"""Stage for replanning a failed run using prior execution context."""
from __future__ import annotations

from adp.models.task import TaskPlan, TaskStatus
from adp.stages.decomposer import decompose


def _summarize_completed_outputs(plan: TaskPlan) -> str:
    completed = [
        f"- {task.output_key}: {task.description}"
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
