"""Tests for adp/stages/reflector.py — per-task semantic reflection."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from adp.stages.reflector import (
    _build_reflection_prompt,
    _parse_verdict,
    has_reflection_failures,
    reflect_plan,
    reflect_task,
    reflection_failure_summary,
    should_use_cloud,
)
from adp.models.task import (
    AnchorType,
    MicroTask,
    ReflectionResult,
    TaskPlan,
    TaskStatus,
)


def _make_task(
    id: str = "t1",
    description: str = "extract a date",
    anchor: AnchorType = AnchorType.OUTPUT,
    depends_on: list[str] | None = None,
    status: TaskStatus = TaskStatus.DONE,
    output: str | None = "some output",
) -> MicroTask:
    return MicroTask(
        id=id,
        description=description,
        system_prompt_template="EXAMPLES:\nInput: a\nOutput: b\n---\nInput: {input_text}\nOutput:",
        input_text="run this",
        output_key=f"key_{id}",
        depends_on=depends_on or [],
        anchor=anchor,
        parallel_group=0,
        status=status,
        output=output,
    )


class TestParseVerdict:
    def test_pass(self):
        passed, reason = _parse_verdict("PASS")
        assert passed is True
        assert reason == "PASS"

    def test_pass_with_trailing_text(self):
        passed, reason = _parse_verdict("PASS\n")
        assert passed is True

    def test_fail_with_dash(self):
        passed, reason = _parse_verdict("FAIL — output is not a valid date")
        assert passed is False
        assert "not a valid date" in reason

    def test_fail_with_hyphen(self):
        passed, reason = _parse_verdict("FAIL - wrong format")
        assert passed is False
        assert "wrong format" in reason

    def test_fail_no_reason(self):
        passed, reason = _parse_verdict("FAIL")
        assert passed is False
        assert reason == "no reason given"

    def test_ambiguous_output(self):
        passed, reason = _parse_verdict("I think this looks good")
        assert passed is False
        assert "ambiguous" in reason


class TestShouldUseCloud:
    def test_code_with_deps_and_verb_uses_cloud(self):
        task = _make_task(
            description="Write the POST /orders endpoint",
            anchor=AnchorType.CODE,
            depends_on=["t1", "t2"],
        )
        assert should_use_cloud(task) is True

    def test_code_without_enough_deps_stays_local(self):
        task = _make_task(
            description="Write the GET endpoint",
            anchor=AnchorType.CODE,
            depends_on=["t1"],
        )
        assert should_use_cloud(task) is False

    def test_non_code_anchor_stays_local(self):
        task = _make_task(
            description="Write a JSON schema",
            anchor=AnchorType.JSON,
            depends_on=["t1", "t2", "t3"],
        )
        assert should_use_cloud(task) is False

    def test_code_without_impl_verb_stays_local(self):
        task = _make_task(
            description="Python version detection",
            anchor=AnchorType.CODE,
            depends_on=["t1", "t2"],
        )
        assert should_use_cloud(task) is False

    def test_code_with_generate_verb_uses_cloud(self):
        task = _make_task(
            description="Generate conftest.py fixtures",
            anchor=AnchorType.CODE,
            depends_on=["t1", "t2"],
        )
        assert should_use_cloud(task) is True


class TestBuildReflectionPrompt:
    def test_contains_task_description(self):
        task = _make_task(description="extract dates from text")
        prompt = _build_reflection_prompt(task)
        assert "extract dates from text" in prompt

    def test_contains_output(self):
        task = _make_task(output='{"date": "2026-01-01"}')
        prompt = _build_reflection_prompt(task)
        assert '{"date": "2026-01-01"}' in prompt

    def test_handles_empty_output(self):
        task = _make_task(output=None)
        prompt = _build_reflection_prompt(task)
        assert "(empty)" in prompt


class TestReflectTask:
    @pytest.mark.asyncio
    async def test_pass_verdict(self):
        task = _make_task(output="def add(a, b): return a + b")
        with patch(
            "adp.stages.reflector.call_local_async",
            return_value="Verdict: PASS",
        ):
            result = await reflect_task(task, use_cloud=False)
        assert result.passed is True
        assert result.task_id == "t1"
        assert result.used_cloud is False

    @pytest.mark.asyncio
    async def test_fail_verdict(self):
        task = _make_task(output="Hello world")
        with patch(
            "adp.stages.reflector.call_local_async",
            return_value="Verdict: FAIL — output is not related to the task",
        ):
            result = await reflect_task(task, use_cloud=False)
        assert result.passed is False
        assert "not related" in result.reason

    @pytest.mark.asyncio
    async def test_cloud_reflection(self):
        task = _make_task(output="def handler(): pass")
        with patch(
            "adp.stages.reflector.call_cloud_async",
            return_value="PASS",
        ):
            result = await reflect_task(task, use_cloud=True)
        assert result.passed is True
        assert result.used_cloud is True

    @pytest.mark.asyncio
    async def test_no_output_returns_fail(self):
        task = _make_task(status=TaskStatus.DONE, output=None)
        result = await reflect_task(task)
        assert result.passed is False
        assert "no output" in result.reason

    @pytest.mark.asyncio
    async def test_pending_task_returns_fail(self):
        task = _make_task(status=TaskStatus.PENDING, output=None)
        result = await reflect_task(task)
        assert result.passed is False

    @pytest.mark.asyncio
    async def test_exception_defaults_to_pass(self):
        """Reflection infrastructure failure should not block the pipeline."""
        task = _make_task(output="some output")
        with patch(
            "adp.stages.reflector.call_local_async",
            side_effect=Exception("connection refused"),
        ):
            result = await reflect_task(task, use_cloud=False)
        assert result.passed is True
        assert "defaulting to PASS" in result.reason

    @pytest.mark.asyncio
    async def test_non_code_task_uses_deterministic_reflection(self):
        task = _make_task(anchor=AnchorType.JSON, output='{"date":"2026-04-08"}')
        with patch("adp.stages.reflector.call_local_async") as mock_local:
            result = await reflect_task(task, use_cloud=False)
        assert result.passed is True
        assert result.reason == "PASS"
        mock_local.assert_not_called()

    @pytest.mark.asyncio
    async def test_code_no_output_false_negative_is_ignored_when_output_present(self):
        task = _make_task(
            anchor=AnchorType.CODE,
            output="def f():\n    return 1\n",
        )
        with patch(
            "adp.stages.reflector.call_local_async",
            return_value="Verdict: FAIL — no output provided",
        ):
            result = await reflect_task(task, use_cloud=False)
        assert result.passed is True


class TestReflectPlan:
    @pytest.mark.asyncio
    async def test_reflects_done_tasks_only(self):
        t1 = _make_task("t1", status=TaskStatus.DONE, output="result1")
        t2 = _make_task("t2", status=TaskStatus.FAILED, output=None)
        t3 = _make_task("t3", status=TaskStatus.DONE, output="result3")
        plan = TaskPlan(tasks=[t1, t2, t3], final_output_keys=[], output_filenames=[])

        with patch(
            "adp.stages.reflector.REFLECT_USE_CLOUD",
            True,
        ), patch(
            "adp.stages.reflector.call_cloud_async",
            return_value="PASS",
        ):
            results = await reflect_plan(plan, {})

        assert len(results) == 2
        assert all(r.passed for r in results)

    @pytest.mark.asyncio
    async def test_callback_fired_for_each_task(self):
        t1 = _make_task("t1", status=TaskStatus.DONE, output="result")
        plan = TaskPlan(tasks=[t1], final_output_keys=[], output_filenames=[])
        reflected = []

        def on_reflected(task, result):
            reflected.append((task.id, result.passed))

        with patch(
            "adp.stages.reflector.REFLECT_USE_CLOUD",
            True,
        ), patch(
            "adp.stages.reflector.call_cloud_async",
            return_value="PASS",
        ):
            await reflect_plan(plan, {}, on_task_reflected=on_reflected)

        assert len(reflected) == 1
        assert reflected[0] == ("t1", True)

    @pytest.mark.asyncio
    async def test_reflect_plan_recovers_missing_task_output_from_context(self):
        t1 = _make_task("t1", status=TaskStatus.DONE, output=None)
        t1.output_key = "date_json"
        plan = TaskPlan(tasks=[t1], final_output_keys=[], output_filenames=[])

        with patch("adp.stages.reflector.REFLECT_USE_CLOUD", True), patch(
            "adp.stages.reflector.call_cloud_async",
            return_value="PASS",
        ):
            results = await reflect_plan(plan, {"date_json": '{"date":"2026-04-08"}'})

        assert len(results) == 1
        assert results[0].passed is True


class TestHelpers:
    def test_has_failures_true(self):
        results = [
            ReflectionResult("t1", True, "PASS"),
            ReflectionResult("t2", False, "wrong output"),
        ]
        assert has_reflection_failures(results) is True

    def test_has_failures_false(self):
        results = [
            ReflectionResult("t1", True, "PASS"),
            ReflectionResult("t2", True, "PASS"),
        ]
        assert has_reflection_failures(results) is False

    def test_failure_summary(self):
        results = [
            ReflectionResult("t1", True, "PASS"),
            ReflectionResult("t2", False, "output is empty"),
            ReflectionResult("t3", False, "wrong format"),
        ]
        summary = reflection_failure_summary(results)
        assert "2 issue(s)" in summary
        assert "t2" in summary
        assert "t3" in summary
