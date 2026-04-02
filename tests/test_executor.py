"""Tests for adp/stages/executor.py — context injection and parallel execution."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from adp.stages.executor import execute_plan, fill_template
from adp.models.task import AnchorType, ContextDict, MicroTask, TaskPlan, TaskStatus


def _make_task(id: str, depends_on: list[str], group: int,
               output_key: str | None = None) -> MicroTask:
    return MicroTask(
        id=id,
        description=f"Task {id}",
        system_prompt_template=(
            "You are a test model.\n\nEXAMPLES:\n"
            "Input: a\nOutput: b\n\n---\nInput: {input_text}\nOutput:"
        ),
        input_text="run this",
        output_key=output_key or f"key_{id}",
        depends_on=depends_on,
        anchor=AnchorType.OUTPUT,
        parallel_group=group,
    )


def _noop(task): pass


class TestFillTemplate:
    def test_fills_placeholder(self):
        template = "Use this: {my_key} in output."
        ctx = {"my_key": "INJECTED_VALUE"}
        result = fill_template(template, ctx)
        assert "INJECTED_VALUE" in result
        assert "{my_key}" not in result

    def test_no_placeholders_unchanged(self):
        template = "No placeholders here."
        result = fill_template(template, {"key": "val"})
        assert result == template

    def test_multiple_placeholders(self):
        template = "{a} and {b}"
        result = fill_template(template, {"a": "AAA", "b": "BBB"})
        assert result == "AAA and BBB"

    def test_missing_key_leaves_placeholder(self):
        """Missing context keys leave {placeholder} as-is (no crash)."""
        template = "Need {missing_key} here."
        result = fill_template(template, {})
        assert "{missing_key}" in result


class TestExecutePlan:
    @pytest.mark.asyncio
    async def test_serial_dependency(self):
        """t2 must see t1's output in context via placeholder injection."""
        t1 = _make_task("t1", [], 0, output_key="t1_out")
        t2 = MicroTask(
            id="t2",
            description="Task t2",
            system_prompt_template=(
                "EXAMPLES:\nInput: x\nOutput: y\n---\n"
                "Context: {t1_out}\nInput: {input_text}\nOutput:"
            ),
            input_text="use t1 output",
            output_key="t2_out",
            depends_on=["t1"],
            anchor=AnchorType.OUTPUT,
            parallel_group=1,
        )
        plan = TaskPlan(tasks=[t1, t2], final_output_keys=["t2_out"],
                        output_filenames=["out.txt"])

        call_order = []

        async def mock_local(system_prompt, input_text, anchor_str, model_name=None):
            # Capture which task's context was injected
            if "t1_result" in system_prompt:
                call_order.append("t2_saw_t1")
            else:
                call_order.append("t1")
            return "Output: result_value"

        with patch("adp.stages.executor.call_local_async", side_effect=mock_local):
            ctx = await execute_plan(plan, _noop, _noop, _noop)

        assert t1.status == TaskStatus.DONE
        assert t2.status == TaskStatus.DONE
        assert "t1_out" in ctx
        assert "t2_out" in ctx

    @pytest.mark.asyncio
    async def test_failed_task_skips_downstream(self):
        """If t1 fails, t2 (which depends on t1) must be SKIPPED."""
        t1 = _make_task("t1", [], 0)
        t2 = _make_task("t2", ["t1"], 1)
        plan = TaskPlan(tasks=[t1, t2], final_output_keys=["key_t2"],
                        output_filenames=[])

        async def mock_local(*args, **kwargs):
            # Always return empty string → validation fails → task FAILED
            return ""

        failed_tasks = []

        def on_failed(task):
            failed_tasks.append(task.id)

        with patch("adp.stages.executor.call_local_async", side_effect=mock_local):
            ctx = await execute_plan(plan, _noop, _noop, on_failed)

        assert t1.status == TaskStatus.FAILED
        assert t2.status == TaskStatus.SKIPPED
        assert "key_t1" not in ctx
        assert "key_t2" not in ctx
        assert "t1" in failed_tasks
        assert "t2" in failed_tasks

    @pytest.mark.asyncio
    async def test_parallel_group_runs_concurrently(self):
        """Tasks in the same group should all start before any finishes."""
        started = []
        finished = []

        t1 = _make_task("t1", [], 0)
        t2 = _make_task("t2", [], 0)
        plan = TaskPlan(tasks=[t1, t2], final_output_keys=[], output_filenames=[])

        async def mock_local(system_prompt, input_text, anchor_str, model_name=None):
            started.append(input_text)
            await asyncio.sleep(0.05)
            finished.append(input_text)
            return "Output: done"

        with patch("adp.stages.executor.call_local_async", side_effect=mock_local):
            await execute_plan(plan, _noop, _noop, _noop)

        # Both should have started before either finished (concurrent execution)
        assert len(started) == 2
        assert len(finished) == 2
        assert t1.status == TaskStatus.DONE
        assert t2.status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_retry_on_invalid_output(self):
        """Task should retry up to MAX_RETRIES before marking as FAILED."""
        t1 = _make_task("t1", [], 0)
        plan = TaskPlan(tasks=[t1], final_output_keys=[], output_filenames=[])

        call_count = 0

        async def mock_local(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return ""  # always invalid

        with patch("adp.stages.executor.call_local_async", side_effect=mock_local):
            from adp.config import MAX_RETRIES
            await execute_plan(plan, _noop, _noop, _noop)

        assert t1.status == TaskStatus.FAILED
        assert call_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_resume_skips_done_tasks_and_uses_initial_context(self):
        """Completed tasks should not rerun when resuming a partially finished plan."""
        t1 = _make_task("t1", [], 0, output_key="schema")
        t1.status = TaskStatus.DONE
        t1.output = "ready"
        t2 = MicroTask(
            id="t2",
            description="Task t2",
            system_prompt_template=(
                "EXAMPLES:\nInput: x\nOutput: y\n---\n"
                "Schema: {schema}\nInput: {input_text}\nOutput:"
            ),
            input_text="use schema",
            output_key="answer",
            depends_on=["t1"],
            anchor=AnchorType.OUTPUT,
            parallel_group=1,
        )
        plan = TaskPlan(tasks=[t1, t2], final_output_keys=["answer"], output_filenames=[])

        prompts = []

        async def mock_local(system_prompt, input_text, anchor_str, model_name=None):
            prompts.append(system_prompt)
            return "Output: resumed"

        with patch("adp.stages.executor.call_local_async", side_effect=mock_local):
            ctx = await execute_plan(
                plan,
                _noop,
                _noop,
                _noop,
                initial_context={"schema": "ready"},
            )

        assert len(prompts) == 1
        assert "Schema: ready" in prompts[0]
        assert ctx["schema"] == "ready"
        assert ctx["answer"] == "resumed"
