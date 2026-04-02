"""Tests for adp/stages/decomposer.py — prompt contract, parsing, and retry logic."""
import json
import pytest
from unittest.mock import AsyncMock, patch

from adp.stages.decomposer import (
    DECOMPOSER_SYSTEM_PROMPT,
    DecompositionError,
    _parse_task_plan,
    decompose,
)
from adp.models.task import AnchorType, TaskStatus


VALID_PLAN_DATA = {
    "tasks": [
        {
            "id": "t1",
            "description": "Extract name",
            "system_prompt_template": (
                "You are a name extractor.\n\nEXAMPLES:\n"
                "Input: foo\nOutput: foo\n\n---\nInput: {input_text}\nOutput:"
            ),
            "input_text": "extract this",
            "output_key": "name",
            "depends_on": [],
            "anchor": "Output:",
            "parallel_group": 0,
        }
    ],
    "final_output_keys": ["name"],
    "output_filenames": ["output.txt"],
}


class TestParseTaskPlan:
    def test_valid_plan(self):
        plan = _parse_task_plan(VALID_PLAN_DATA)
        assert len(plan.tasks) == 1
        assert plan.tasks[0].id == "t1"
        assert plan.tasks[0].anchor == AnchorType.OUTPUT
        assert plan.final_output_keys == ["name"]
        assert plan.output_filenames == ["output.txt"]

    def test_missing_examples_raises(self):
        data = {
            "tasks": [{
                **VALID_PLAN_DATA["tasks"][0],
                "system_prompt_template": "No examples here at all.",
            }],
            "final_output_keys": ["name"],
            "output_filenames": ["out.txt"],
        }
        with pytest.raises(DecompositionError, match="EXAMPLES:"):
            _parse_task_plan(data)

    def test_invalid_anchor_raises(self):
        data = {
            "tasks": [{
                **VALID_PLAN_DATA["tasks"][0],
                "anchor": "INVALID:",
            }],
            "final_output_keys": ["name"],
            "output_filenames": ["out.txt"],
        }
        with pytest.raises(ValueError):
            _parse_task_plan(data)

    def test_missing_field_raises(self):
        bad = {"tasks": [{"id": "t1"}], "final_output_keys": [], "output_filenames": []}
        with pytest.raises((KeyError, ValueError)):
            _parse_task_plan(bad)


class TestDecomposerPrompt:
    def test_prompt_requires_cloud_to_plan_for_local_coder(self):
        assert "PLAN for a small local model" in DECOMPOSER_SYSTEM_PROMPT
        assert "Never create a single task that asks the local model to write an entire app" in (
            DECOMPOSER_SYSTEM_PROMPT
        )
        assert 'GOOD: "Write GET / endpoint for app.py"' in DECOMPOSER_SYSTEM_PROMPT
        assert 'BAD:  "Write Flask application code"' in DECOMPOSER_SYSTEM_PROMPT


class TestDecomposeRetry:
    @pytest.mark.asyncio
    async def test_retries_on_invalid_json(self):
        """Should retry when model returns non-JSON, succeed on second attempt."""
        valid_json = json.dumps(VALID_PLAN_DATA)
        call_count = 0

        async def mock_call(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "not valid json at all"
            return valid_json

        with patch("adp.stages.decomposer.call_cloud_with_history", side_effect=mock_call):
            plan = await decompose("test prompt")
            assert plan.tasks[0].id == "t1"
            assert call_count == 2  # failed once, succeeded on retry

    @pytest.mark.asyncio
    async def test_reports_retry_reason_via_callback(self):
        """Should surface each decomposition retry reason to the caller."""
        valid_json = json.dumps(VALID_PLAN_DATA)
        retries: list[tuple[int, str]] = []
        call_count = 0

        async def mock_call(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "not valid json at all"
            return valid_json

        with patch("adp.stages.decomposer.call_cloud_with_history", side_effect=mock_call):
            await decompose(
                "test prompt",
                on_retry=lambda attempt, reason: retries.append((attempt, reason)),
            )

        assert len(retries) == 1
        assert retries[0][0] == 1
        assert "Expecting value" in retries[0][1]

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Should raise DecompositionError after 3 failed attempts."""
        async def mock_call(messages, **kwargs):
            return "always bad json {"

        with patch("adp.stages.decomposer.call_cloud_with_history", side_effect=mock_call):
            with pytest.raises(DecompositionError, match="3 attempts"):
                await decompose("test prompt")
