"""Tests for TUI run summary generation."""
from __future__ import annotations

from adp.models.task import AnchorType, MicroTask, TaskStatus
from adp.tui.app import _build_run_summary


def _task(task_id: str, status: TaskStatus) -> MicroTask:
    return MicroTask(
        id=task_id,
        description=f"Task {task_id}",
        system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
        input_text="run",
        output_key=f"out_{task_id}",
        depends_on=[],
        anchor=AnchorType.OUTPUT,
        parallel_group=0,
        status=status,
    )


def test_build_run_summary_for_fast_path():
    summary = _build_run_summary([], [])
    assert "Fast path response returned" in summary


def test_build_run_summary_with_tasks_and_tools():
    tasks = [
        _task("t1", TaskStatus.DONE),
        _task("t2", TaskStatus.DONE),
        _task("t3", TaskStatus.FAILED),
        _task("t4", TaskStatus.SKIPPED),
    ]
    tool_history = [
        "t1 call: search",
        "t1 done: search",
        "t2 call: read_text_file",
    ]
    summary = _build_run_summary(tasks, tool_history)
    assert "Tasks: 2/4 done, 1 failed, 1 skipped." in summary
    assert "Tools called: 2 call(s) across 2 tool(s): read_text_file, search." in summary

