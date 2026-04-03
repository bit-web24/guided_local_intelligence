"""Tests for the LangGraph supervisor loop."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from adp.agent_graph import run_agent_graph
from adp.engine.run_store import generate_run_id, save_run_state
from adp.models.task import AnchorType, MicroTask, TaskPlan, TaskStatus


@dataclass
class _Callbacks:
    stages: list[str] = field(default_factory=list)
    plans: list[TaskPlan] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    completed: list[tuple[list[tuple[str, int]], str, str | None]] = field(default_factory=list)
    retries: list[tuple[int, str]] = field(default_factory=list)

    def on_stage(self, stage: str) -> None:
        self.stages.append(stage)

    def on_plan_ready(self, plan: TaskPlan) -> None:
        self.plans.append(plan)

    def on_decomposition_retry(self, attempt: int, reason: str) -> None:
        self.retries.append((attempt, reason))

    def on_task_start(self, task: MicroTask) -> None:
        return None

    def on_task_done(self, task: MicroTask) -> None:
        return None

    def on_task_failed(self, task: MicroTask) -> None:
        return None

    def on_complete(self, written: list[tuple[str, int]], output_dir: str, stdout_text: str | None = None) -> None:
        self.completed.append((written, output_dir, stdout_text))

    def on_error(self, message: str) -> None:
        self.errors.append(message)


def _make_text_plan(output_key: str = "answer") -> TaskPlan:
    return TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Task t1",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key=output_key,
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
            )
        ],
        final_output_keys=[output_key],
        output_filenames=[],
        write_to_file=False,
    )


@pytest.mark.asyncio
async def test_graph_replans_after_failed_execution(tmp_path):
    callbacks = _Callbacks()
    first_plan = _make_text_plan()
    second_plan = _make_text_plan()

    async def execute_side_effect(plan, *args, **kwargs):
        if plan is first_plan:
            plan.tasks[0].status = TaskStatus.FAILED
            plan.tasks[0].error = "validation failed"
            return {}
        plan.tasks[0].status = TaskStatus.DONE
        plan.tasks[0].output = "final answer"
        return {"answer": "final answer"}

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=first_plan)), \
         patch("adp.agent_graph.replan", AsyncMock(return_value=second_plan)) as replan_mock, \
         patch("adp.agent_graph.execute_plan", AsyncMock(side_effect=execute_side_effect)), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.assemble", AsyncMock(return_value={"__stdout__": "done"})):
        result = await run_agent_graph(
            user_prompt="Say hello",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=None,
            tool_registry=None,
        )

    assert result.files["__stdout__"] == "done"
    assert "REPLANNING" in callbacks.stages
    assert replan_mock.await_count == 1


@pytest.mark.asyncio
async def test_graph_resumes_from_persisted_run_state(tmp_path):
    callbacks = _Callbacks()
    run_id = generate_run_id()
    plan = TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Task t1",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="schema",
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
                status=TaskStatus.DONE,
                output="schema-value",
            ),
            MicroTask(
                id="t2",
                description="Task t2",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nContext: {schema}\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="answer",
                depends_on=["t1"],
                anchor=AnchorType.OUTPUT,
                parallel_group=1,
                status=TaskStatus.PENDING,
            ),
        ],
        final_output_keys=["answer"],
        output_filenames=[],
        write_to_file=False,
    )
    save_run_state(
        output_dir=str(tmp_path),
        run_id=run_id,
        user_prompt="Resume me",
        plan=plan,
        context={"schema": "schema-value"},
        files={},
        status="executed",
        replan_count=0,
        max_replans=2,
    )

    async def execute_side_effect(plan, *args, **kwargs):
        assert kwargs["initial_context"]["schema"] == "schema-value"
        plan.tasks[1].status = TaskStatus.DONE
        plan.tasks[1].output = "resumed answer"
        return {"schema": "schema-value", "answer": "resumed answer"}

    with patch("adp.agent_graph.execute_plan", AsyncMock(side_effect=execute_side_effect)) as execute_mock, \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.assemble", AsyncMock(return_value={"__stdout__": "done"})):
        result = await run_agent_graph(
            user_prompt="",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=None,
            tool_registry=None,
            resume_run_id=run_id,
        )

    assert result.context["answer"] == "resumed answer"
    assert execute_mock.await_count == 1
    assert "RESUMING" in callbacks.stages
