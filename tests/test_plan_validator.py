"""Tests for strict task-plan validation."""
from __future__ import annotations

import pytest

from adp.engine.plan_validator import PlanValidationError, validate_task_plan
from adp.models.task import AnchorType, MicroTask, TaskPlan


def _make_task(
    task_id: str,
    output_key: str,
    depends_on: list[str] | None = None,
    template: str | None = None,
    mcp_tools: list[str] | None = None,
) -> MicroTask:
    default_template = (
        "You are a test task.\n\n"
        "EXAMPLES:\n"
        "Input: foo\n"
        "Output: bar\n\n"
        "---\n"
        "Input: {input_text}\n"
        "Output:"
    )
    return MicroTask(
        id=task_id,
        description=f"Task {task_id}",
        system_prompt_template=template or default_template,
        input_text="run",
        output_key=output_key,
        depends_on=depends_on or [],
        anchor=AnchorType.OUTPUT,
        parallel_group=0 if not depends_on else 1,
        mcp_tools=mcp_tools or [],
    )


def test_valid_plan_passes():
    t1 = _make_task("t1", "schema_json")
    t2 = _make_task(
        "t2",
        "endpoint_code",
        depends_on=["t1"],
        template=(
            "You are a test task.\n\n"
            "EXAMPLES:\n"
            "Context: old_value\n"
            "Input: foo\n"
            "Output: bar\n\n"
            "---\n"
            "Context: {schema_json}\n"
            "Input: {input_text}\n"
            "Output:"
        ),
    )
    plan = TaskPlan(
        tasks=[t1, t2],
        final_output_keys=["endpoint_code"],
        output_filenames=["app.py"],
        write_to_file=True,
    )

    validate_task_plan(plan)


def test_duplicate_output_keys_fail():
    plan = TaskPlan(
        tasks=[_make_task("t1", "shared"), _make_task("t2", "shared")],
        final_output_keys=["shared"],
        output_filenames=["out.txt"],
        write_to_file=True,
    )

    with pytest.raises(PlanValidationError, match="output keys must be unique"):
        validate_task_plan(plan)


def test_template_must_end_with_anchor():
    task = _make_task(
        "t1",
        "answer",
        template="EXAMPLES:\nInput: x\nOutput: y\n---\nOutput:\nextra",
    )
    plan = TaskPlan(
        tasks=[task],
        final_output_keys=["answer"],
        output_filenames=["out.txt"],
        write_to_file=True,
    )

    with pytest.raises(PlanValidationError, match="must end with 'Output:'"):
        validate_task_plan(plan)


def test_dependency_placeholder_required():
    t1 = _make_task("t1", "schema_json")
    t2 = _make_task(
        "t2",
        "endpoint_code",
        depends_on=["t1"],
        template=(
            "EXAMPLES:\n"
            "Input: foo\n"
            "Output: bar\n"
            "---\n"
            "Input: {input_text}\n"
            "Output:"
        ),
    )
    plan = TaskPlan(
        tasks=[t1, t2],
        final_output_keys=["endpoint_code"],
        output_filenames=["app.py"],
        write_to_file=True,
    )

    with pytest.raises(PlanValidationError, match="depends on outputs not referenced"):
        validate_task_plan(plan)


def test_unknown_placeholder_fails():
    task = _make_task(
        "t1",
        "answer",
        template=(
            "EXAMPLES:\n"
            "Input: foo\n"
            "Output: bar\n"
            "---\n"
            "Context: {made_up_value}\n"
            "Input: {input_text}\n"
            "Output:"
        ),
    )
    plan = TaskPlan(
        tasks=[task],
        final_output_keys=["answer"],
        output_filenames=["out.txt"],
        write_to_file=True,
    )

    with pytest.raises(PlanValidationError, match="unknown placeholders"):
        validate_task_plan(plan)


def test_mcp_tool_placeholder_required():
    task = _make_task(
        "t1",
        "answer",
        mcp_tools=["read_text_file"],
    )
    plan = TaskPlan(
        tasks=[task],
        final_output_keys=["answer"],
        output_filenames=["out.txt"],
        write_to_file=True,
    )

    with pytest.raises(PlanValidationError, match="does not reference their results"):
        validate_task_plan(plan)


def test_final_output_keys_must_exist():
    plan = TaskPlan(
        tasks=[_make_task("t1", "answer")],
        final_output_keys=["missing_key"],
        output_filenames=["out.txt"],
        write_to_file=True,
    )

    with pytest.raises(PlanValidationError, match="unknown task outputs"):
        validate_task_plan(plan)


def test_text_mode_requires_no_filenames():
    plan = TaskPlan(
        tasks=[_make_task("t1", "answer")],
        final_output_keys=["answer"],
        output_filenames=["out.txt"],
        write_to_file=False,
    )

    with pytest.raises(PlanValidationError, match="write_to_file=False"):
        validate_task_plan(plan)


def test_absolute_output_filename_fails():
    plan = TaskPlan(
        tasks=[_make_task("t1", "answer")],
        final_output_keys=["answer"],
        output_filenames=["/tmp/out.txt"],
        write_to_file=True,
    )

    with pytest.raises(PlanValidationError, match="relative paths within the output directory"):
        validate_task_plan(plan)


def test_parent_directory_output_filename_fails():
    plan = TaskPlan(
        tasks=[_make_task("t1", "answer")],
        final_output_keys=["answer"],
        output_filenames=["../out.txt"],
        write_to_file=True,
    )

    with pytest.raises(PlanValidationError, match="relative paths within the output directory"):
        validate_task_plan(plan)


def test_write_to_file_rejects_status_like_final_output_keys():
    task = _make_task("t1", "file_created_status")
    task.description = "Create output file in info directory"
    plan = TaskPlan(
        tasks=[task],
        final_output_keys=["file_created_status"],
        output_filenames=["info/quantization.txt"],
        write_to_file=True,
    )

    with pytest.raises(PlanValidationError, match="file-content fragments"):
        validate_task_plan(plan)


def test_write_to_file_accepts_content_like_final_output_keys():
    task = _make_task("t1", "quantization_web_summary")
    task.description = "Write quantization summary content for info/quantization.txt"
    plan = TaskPlan(
        tasks=[task],
        final_output_keys=["quantization_web_summary"],
        output_filenames=["info/quantization.txt"],
        write_to_file=True,
    )

    validate_task_plan(plan)
