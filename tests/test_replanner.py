"""Tests for partial replanning that preserves completed work."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from adp.models.task import AnchorType, MicroTask, TaskPlan, TaskStatus
from adp.stages.replanner import build_preserved_context, get_completed_tasks, replan


def _make_plan() -> TaskPlan:
    return TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Fetch web data",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="web_results",
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
                status=TaskStatus.DONE,
                output="done",
            ),
            MicroTask(
                id="t2",
                description="Write summary",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="final_summary",
                depends_on=["t1"],
                anchor=AnchorType.OUTPUT,
                parallel_group=1,
                status=TaskStatus.FAILED,
                error="validation failed",
            ),
        ],
        final_output_keys=["final_summary"],
        output_filenames=["out.txt"],
        write_to_file=True,
    )


def test_get_completed_tasks_returns_only_done_tasks_with_output():
    plan = _make_plan()
    completed = get_completed_tasks(plan)

    assert [task.id for task in completed] == ["t1"]


def test_build_preserved_context_keeps_only_completed_outputs():
    plan = _make_plan()
    context = {
        "web_results": "done",
        "final_summary": "bad",
        "t1_read_text_file_result": "ephemeral",
    }

    preserved = build_preserved_context(plan, context)
    assert preserved == {
        "web_results": "done",
        "t1_read_text_file_result": "ephemeral",
    }


@pytest.mark.asyncio
async def test_replan_requests_only_remaining_work_and_preserves_completed_tasks():
    previous_plan = _make_plan()
    merged_plan = TaskPlan(
        tasks=[
            previous_plan.tasks[0],
            MicroTask(
                id="t3",
                description="Write corrected summary",
                system_prompt_template=(
                    "EXAMPLES:\nInput: x\nOutput: y\n---\nContext: {web_results}\nInput: {input_text}\nOutput:"
                ),
                input_text="run",
                output_key="final_summary",
                depends_on=["t1"],
                anchor=AnchorType.OUTPUT,
                parallel_group=1,
            ),
        ],
        final_output_keys=["final_summary"],
        output_filenames=["out.txt"],
        write_to_file=True,
    )

    with patch("adp.stages.replanner.decompose", AsyncMock(return_value=merged_plan)) as decompose_mock:
        plan = await replan(
            "Summarize the web results",
            previous_plan,
            tool_registry=None,
            project_dir="/tmp/project",
        )

    assert plan is merged_plan
    kwargs = decompose_mock.await_args.kwargs
    assert kwargs["existing_tasks"] == [previous_plan.tasks[0]]
    assert kwargs["final_output_keys_override"] == ["final_summary"]
    assert kwargs["output_filenames_override"] == ["out.txt"]
    assert kwargs["write_to_file_override"] is True
    assert "Generate ONLY the remaining corrective micro-tasks" in decompose_mock.await_args.args[0]
