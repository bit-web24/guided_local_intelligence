"""Tests for adp/stages/decomposer.py — prompt contract, parsing, and retry logic."""
import json
import pytest
from unittest.mock import AsyncMock, patch

from adp.stages.decomposer import (
    DECOMPOSER_SYSTEM_PROMPT,
    DecompositionError,
    _MCP_TOOL_BLOCK_TEMPLATE,
    _build_retry_feedback,
    _parse_task_plan,
    decompose,
)
from adp.config import DECOMPOSITION_MAX_RETRIES
from adp.models.task import AnchorType, MicroTask, TaskStatus


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

    def test_repairs_cross_task_mcp_placeholder_to_dependency_output_key(self):
        data = {
            "tasks": [
                {
                    "id": "t1",
                    "description": "Summarize file",
                    "system_prompt_template": (
                        "EXAMPLES:\n"
                        "File: abc\n"
                        "Output: summary\n"
                        "---\n"
                        "File: {t1_read_text_file_result}\n"
                        "Input: {input_text}\n"
                        "Output:"
                    ),
                    "input_text": "summarize",
                    "output_key": "file_summary",
                    "depends_on": [],
                    "anchor": "Output:",
                    "parallel_group": 0,
                    "mcp_tools": ["read_text_file"],
                },
                {
                    "id": "t2",
                    "description": "Write patch",
                    "system_prompt_template": (
                        "EXAMPLES:\n"
                        "Summary: old\n"
                        "Code: patch\n"
                        "---\n"
                        "Summary: {t1_read_text_file_result}\n"
                        "Input: {input_text}\n"
                        "Code:"
                    ),
                    "input_text": "write patch",
                    "output_key": "patch_code",
                    "depends_on": ["t1"],
                    "anchor": "Code:",
                    "parallel_group": 1,
                },
            ],
            "final_output_keys": ["patch_code"],
            "output_filenames": ["main.py"],
        }

        plan = _parse_task_plan(data)
        assert "{file_summary}" in plan.tasks[1].system_prompt_template
        assert "{t1_read_text_file_result}" not in plan.tasks[1].system_prompt_template

    def test_repairs_prefixed_dependency_placeholder_to_dependency_output_key(self):
        data = {
            "tasks": [
                {
                    **VALID_PLAN_DATA["tasks"][0],
                    "output_key": "file_content",
                },
                {
                    "id": "t2",
                    "description": "Use prior file content",
                    "system_prompt_template": (
                        "EXAMPLES:\n"
                        "Context: old\n"
                        "Output: next\n"
                        "---\n"
                        "Context: {t1_file_content}\n"
                        "Input: {input_text}\n"
                        "Output:"
                    ),
                    "input_text": "continue",
                    "output_key": "final_answer",
                    "depends_on": ["t1"],
                    "anchor": "Output:",
                    "parallel_group": 1,
                },
            ],
            "final_output_keys": ["final_answer"],
            "output_filenames": ["output.txt"],
        }

        plan = _parse_task_plan(data)
        assert "{file_content}" in plan.tasks[1].system_prompt_template
        assert "{t1_file_content}" not in plan.tasks[1].system_prompt_template

    def test_repairs_missing_dependency_placeholder_by_injecting_context(self):
        data = {
            "tasks": [
                {
                    **VALID_PLAN_DATA["tasks"][0],
                    "output_key": "write_status",
                },
                {
                    "id": "t2",
                    "description": "Use prior status",
                    "system_prompt_template": (
                        "EXAMPLES:\n"
                        "Input: foo\n"
                        "Output: bar\n"
                        "---\n"
                        "Input: {input_text}\n"
                        "Output:"
                    ),
                    "input_text": "continue",
                    "output_key": "final_answer",
                    "depends_on": ["t1"],
                    "anchor": "Output:",
                    "parallel_group": 1,
                },
            ],
            "final_output_keys": ["final_answer"],
            "output_filenames": ["output.txt"],
        }

        plan = _parse_task_plan(data)
        assert "Dependency write_status:" in plan.tasks[1].system_prompt_template
        assert "{write_status}" in plan.tasks[1].system_prompt_template

    def test_parse_task_plan_can_merge_existing_tasks_for_partial_replan(self):
        existing_task = MicroTask(
            id="t1",
            description="Existing schema",
            system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
            input_text="run",
            output_key="schema_json",
            depends_on=[],
            anchor=AnchorType.OUTPUT,
            parallel_group=0,
            status=TaskStatus.DONE,
            output="schema",
        )
        data = {
            "tasks": [
                {
                    "id": "t2",
                    "description": "Write endpoint",
                    "system_prompt_template": (
                        "EXAMPLES:\n"
                        "Schema: old\n"
                        "Code: new\n"
                        "---\n"
                        "Schema: {schema_json}\n"
                        "Input: {input_text}\n"
                        "Code:"
                    ),
                    "input_text": "write endpoint",
                    "output_key": "endpoint_code",
                    "depends_on": ["t1"],
                    "anchor": "Code:",
                    "parallel_group": 1,
                }
            ],
            "final_output_keys": ["endpoint_code"],
            "output_filenames": ["ignored.py"],
            "write_to_file": False,
        }

        plan = _parse_task_plan(
            data,
            existing_tasks=[existing_task],
            final_output_keys_override=["endpoint_code"],
            output_filenames_override=["app.py"],
            write_to_file_override=True,
        )

        assert [task.id for task in plan.tasks] == ["t1", "t2"]
        assert plan.output_filenames == ["app.py"]
        assert plan.write_to_file is True

    def test_partial_replan_remaps_duplicate_task_ids_and_dependencies(self):
        existing_task = MicroTask(
            id="t1",
            description="Existing schema",
            system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
            input_text="run",
            output_key="schema_json",
            depends_on=[],
            anchor=AnchorType.OUTPUT,
            parallel_group=0,
            status=TaskStatus.DONE,
            output="schema",
        )
        data = {
            "tasks": [
                {
                    "id": "t1",
                    "description": "Read current file",
                    "system_prompt_template": (
                        "EXAMPLES:\n"
                        "File: old\n"
                        "Output: note\n"
                        "---\n"
                        "File: {t1_read_text_file_result}\n"
                        "Input: {input_text}\n"
                        "Output:"
                    ),
                    "input_text": "inspect",
                    "output_key": "file_note",
                    "depends_on": [],
                    "anchor": "Output:",
                    "parallel_group": 1,
                    "mcp_tools": ["read_text_file"],
                },
                {
                    "id": "t2",
                    "description": "Write endpoint",
                    "system_prompt_template": (
                        "EXAMPLES:\n"
                        "Context: old\n"
                        "Code: new\n"
                        "---\n"
                        "Context: {file_note}\n"
                        "Input: {input_text}\n"
                        "Code:"
                    ),
                    "input_text": "write endpoint",
                    "output_key": "endpoint_code",
                    "depends_on": ["t1"],
                    "anchor": "Code:",
                    "parallel_group": 2,
                },
            ],
            "final_output_keys": ["endpoint_code"],
            "output_filenames": ["app.py"],
        }

        plan = _parse_task_plan(
            data,
            existing_tasks=[existing_task],
        )

        assert [task.id for task in plan.tasks] == ["t1", "t2", "t3"]
        assert "{t2_read_text_file_result}" in plan.tasks[1].system_prompt_template
        assert plan.tasks[2].depends_on == ["t2"]

    def test_partial_replan_remaps_duplicate_output_keys_and_final_outputs(self):
        existing_task = MicroTask(
            id="t1",
            description="Existing schema",
            system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
            input_text="run",
            output_key="endpoint_code",
            depends_on=[],
            anchor=AnchorType.OUTPUT,
            parallel_group=0,
            status=TaskStatus.DONE,
            output="existing endpoint",
        )
        data = {
            "tasks": [
                {
                    "id": "t2",
                    "description": "Repair endpoint",
                    "system_prompt_template": (
                        "EXAMPLES:\n"
                        "Input: old\n"
                        "Code: new\n"
                        "---\n"
                        "Input: {input_text}\n"
                        "Code:"
                    ),
                    "input_text": "repair endpoint",
                    "output_key": "endpoint_code",
                    "depends_on": [],
                    "anchor": "Code:",
                    "parallel_group": 1,
                }
            ],
            "final_output_keys": ["endpoint_code"],
            "output_filenames": ["app.py"],
        }

        plan = _parse_task_plan(
            data,
            existing_tasks=[existing_task],
        )

        assert plan.tasks[1].output_key == "endpoint_code_2"
        assert plan.final_output_keys == ["endpoint_code_2"]


class TestDecomposerPrompt:
    def test_prompt_requires_cloud_to_plan_for_local_coder(self):
        assert "PLAN for a small local model" in DECOMPOSER_SYSTEM_PROMPT
        assert "Never create a single task that asks the local model to write an entire app" in (
            DECOMPOSER_SYSTEM_PROMPT
        )
        assert 'GOOD: "Write GET / endpoint for app.py"' in DECOMPOSER_SYSTEM_PROMPT
        assert 'BAD:  "Write Flask application code"' in DECOMPOSER_SYSTEM_PROMPT

    def test_prompt_requires_atomic_specialist_micro_tasks(self):
        assert "One model call should answer ONE atomic question only." in DECOMPOSER_SYSTEM_PROMPT
        assert 'NEVER create a task like "extract everything"' in DECOMPOSER_SYSTEM_PROMPT
        assert "detect intent label only" in DECOMPOSER_SYSTEM_PROMPT
        assert "extract one entity only" in DECOMPOSER_SYSTEM_PROMPT
        assert "build exact JSON arguments only" in DECOMPOSER_SYSTEM_PROMPT

    def test_prompt_applies_specialist_principle_to_code_generation(self):
        assert "For code-generation requests, use the SAME specialist principle" in (
            DECOMPOSER_SYSTEM_PROMPT
        )
        assert "define one route or one file skeleton" in DECOMPOSER_SYSTEM_PROMPT
        assert '"generate all CRUD endpoints in one task"' in DECOMPOSER_SYSTEM_PROMPT


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

    def test_retry_feedback_mentions_examples_and_local_micro_tasks(self):
        message = _build_retry_feedback(
            DecompositionError(
                "Task 't4' system_prompt_template missing 'EXAMPLES:' section. "
                "This is non-negotiable — all templates must contain few-shot examples."
            )
        )

        assert "small local models" in message
        assert "micro-granular" in message
        assert "Every task must contain 3 to 5 realistic few-shot examples" in message
        assert "missing EXAMPLES error is non-negotiable" in message

    @pytest.mark.asyncio
    async def test_retry_message_injects_missing_examples_guidance(self):
        invalid_then_valid = [
            json.dumps({
                "tasks": [
                    {
                        **VALID_PLAN_DATA["tasks"][0],
                        "system_prompt_template": "No examples here at all.",
                    }
                ],
                "final_output_keys": ["name"],
                "output_filenames": ["output.txt"],
            }),
            json.dumps(VALID_PLAN_DATA),
        ]

        seen_messages: list[list[dict]] = []

        async def mock_call(messages, **kwargs):
            seen_messages.append(messages)
            return invalid_then_valid[len(seen_messages) - 1]

        with patch("adp.stages.decomposer.call_cloud_with_history", side_effect=mock_call):
            plan = await decompose("test prompt")

        assert plan.tasks[0].id == "t1"
        retry_user_message = seen_messages[1][-1]["content"]
        assert "missing EXAMPLES error is non-negotiable" in retry_user_message
        assert "small local models" in retry_user_message
        assert "Return ONLY valid JSON matching the schema" in retry_user_message

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """Should raise DecompositionError after the configured retry limit."""
        async def mock_call(messages, **kwargs):
            return "always bad json {"

        with patch("adp.stages.decomposer.call_cloud_with_history", side_effect=mock_call):
            with pytest.raises(
                DecompositionError,
                match=rf"{DECOMPOSITION_MAX_RETRIES} attempts",
            ):
                await decompose("test prompt")

    @pytest.mark.asyncio
    async def test_uses_configured_decomposition_retry_count(self):
        call_count = 0

        async def mock_call(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            return "always bad json {"

        with patch("adp.stages.decomposer.call_cloud_with_history", side_effect=mock_call):
            with pytest.raises(DecompositionError):
                await decompose("test prompt")

        assert call_count == DECOMPOSITION_MAX_RETRIES
