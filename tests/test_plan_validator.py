"""Tests for adp/engine/plan_validator.py."""
import pytest

from adp.engine.plan_validator import PlanValidationError, validate_task_plan
from adp.models.task import AnchorType, MicroTask, TaskKind, TaskPlan


def _task(
    task_id: str,
    output_key: str,
    *,
    depends_on: list[str] | None = None,
    template: str | None = None,
) -> MicroTask:
    return MicroTask(
        id=task_id,
        description=f"Task {task_id}",
        system_prompt_template=template or "EXAMPLES:\nInput: a\nOutput: b\n---\nInput: {input_text}\nOutput:",
        input_text="run",
        output_key=output_key,
        depends_on=depends_on or [],
        anchor=AnchorType.OUTPUT,
        parallel_group=0 if not depends_on else 1,
        task_kind=TaskKind.TRANSFORM,
    )


def test_validate_task_plan_accepts_consistent_plan():
    t1 = _task("t1", "schema")
    t2 = _task(
        "t2",
        "endpoint",
        depends_on=["t1"],
        template="EXAMPLES:\nInput: a\nOutput: b\n---\nSchema: {schema}\nInput: {input_text}\nOutput:",
    )
    plan = TaskPlan(tasks=[t1, t2], final_output_keys=["endpoint"], output_filenames=["main.py"])
    assert validate_task_plan(plan) is plan


def test_validate_task_plan_rejects_unknown_placeholder():
    t1 = _task(
        "t1",
        "schema",
        template="EXAMPLES:\nInput: a\nOutput: b\n---\nNeed: {missing}\nInput: {input_text}\nOutput:",
    )
    plan = TaskPlan(tasks=[t1], final_output_keys=["schema"], output_filenames=["out.txt"])
    with pytest.raises(PlanValidationError, match="unknown placeholders"):
        validate_task_plan(plan)


def test_validate_task_plan_rejects_missing_dependency_for_placeholder():
    t1 = _task("t1", "schema")
    t2 = _task(
        "t2",
        "endpoint",
        template="EXAMPLES:\nInput: a\nOutput: b\n---\nSchema: {schema}\nInput: {input_text}\nOutput:",
    )
    plan = TaskPlan(tasks=[t1, t2], final_output_keys=["endpoint"], output_filenames=["main.py"])
    with pytest.raises(PlanValidationError, match="without matching dependencies"):
        validate_task_plan(plan)


def test_validate_task_plan_rejects_unknown_final_output_key():
    t1 = _task("t1", "schema")
    plan = TaskPlan(tasks=[t1], final_output_keys=["missing"], output_filenames=["out.txt"])
    with pytest.raises(PlanValidationError, match="final_output_key"):
        validate_task_plan(plan)
