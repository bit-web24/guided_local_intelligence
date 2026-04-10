"""Tests for prompt clarification before planning."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from adp.config import get_model_config
from adp.engine.clarifier import clarify_prompt_async, revise_clarified_prompt_async


@pytest.mark.asyncio
async def test_clarifier_proceeds_without_question():
    with patch(
        "adp.engine.clarifier.call_local_async",
        new=AsyncMock(
            side_effect=[
                'JSON: {"needs_clarification": false, "reason_label": "enough_information"}',
            ]
        ),
    ) as mock_call:
        result = await clarify_prompt_async(
            "Do the task",
            ask_user=AsyncMock(),
        )

    assert result is not None
    assert result.clarified_prompt == "Do the task"
    assert result.clarification_turns_used == 0
    assert mock_call.await_count == 1
    assert mock_call.await_args.kwargs["stage_name"] == "clarifier:detect"
    assert mock_call.await_args.kwargs["model_name"] == get_model_config().local_general


@pytest.mark.asyncio
async def test_clarifier_asks_then_merges():
    ask_user = AsyncMock(return_value="Use info/quantization.md")
    responses = [
        'JSON: {"needs_clarification": true, "reason_label": "missing_output_filename"}',
        'JSON: {"question": "What filename should I use for the output file?"}',
        'JSON: {"needs_clarification": false, "reason_label": "enough_information"}',
        'JSON: {"clarified_prompt": "Search the web for quantization in LLMs and write the content to info/quantization.md."}',
    ]

    with patch(
        "adp.engine.clarifier.call_local_async",
        new=AsyncMock(side_effect=responses),
    ) as local_mock, patch(
        "adp.engine.clarifier.call_cloud_async",
        new=AsyncMock(
            return_value='JSON: {"clarified_prompt": "Search the web for quantization in LLMs and write the content to info/quantization.md."}'
        ),
    ) as cloud_mock:
        result = await clarify_prompt_async(
            "Search the web for quantization in LLMs and write it to a file.",
            ask_user=ask_user,
        )

    assert result is not None
    assert result.clarified_prompt == "Search the web for quantization in LLMs and write the content to info/quantization.md."
    assert result.clarification_turns_used == 1
    ask_user.assert_awaited_once()
    stage_names = [call.kwargs["stage_name"] for call in local_mock.await_args_list] + [cloud_mock.await_args.kwargs["stage_name"]]
    assert stage_names == [
        "clarifier:detect",
        "clarifier:question",
        "clarifier:detect",
        "clarifier:merge",
    ]


@pytest.mark.asyncio
async def test_clarifier_forces_merge_after_max_rounds():
    ask_user = AsyncMock(side_effect=["a1", "a2", "a3"])
    responses = [
        'JSON: {"needs_clarification": true, "reason_label": "r1"}',
        'JSON: {"question": "q1"}',
        'JSON: {"needs_clarification": true, "reason_label": "r2"}',
        'JSON: {"question": "q2"}',
        'JSON: {"needs_clarification": true, "reason_label": "r3"}',
        'JSON: {"question": "q3"}',
        'JSON: {"needs_clarification": true, "reason_label": "still_missing"}',
        'JSON: {"clarified_prompt": "Final clarified prompt."}',
    ]

    with patch(
        "adp.engine.clarifier.call_local_async",
        new=AsyncMock(side_effect=responses),
    ) as local_mock, patch(
        "adp.engine.clarifier.call_cloud_async",
        new=AsyncMock(
            return_value='JSON: {"clarified_prompt": "Final clarified prompt."}'
        ),
    ) as cloud_mock:
        result = await clarify_prompt_async(
            "Initial prompt",
            ask_user=ask_user,
            max_rounds=3,
        )

    assert result is not None
    assert result.clarified_prompt == "Final clarified prompt."
    assert result.clarification_turns_used == 3
    assert ask_user.await_count == 3
    stage_names = [call.kwargs["stage_name"] for call in local_mock.await_args_list] + [cloud_mock.await_args.kwargs["stage_name"]]
    assert stage_names[-2:] == ["clarifier:question", "clarifier:merge"]


@pytest.mark.asyncio
async def test_revise_clarified_prompt_incorporates_extra_user_input():
    with patch(
        "adp.engine.clarifier.call_cloud_async",
        new=AsyncMock(
            return_value='JSON: {"clarified_prompt": "Search the web for quantization in LLMs, summarize with markdown headings, and write the content to info/quantization.md."}'
        ),
    ) as mock_call:
        result = await revise_clarified_prompt_async(
            "Search the web for quantization in LLMs and write the content to info/quantization.md.",
            "Make it markdown with headings.",
        )

    assert "markdown headings" in result
    assert mock_call.await_args.kwargs["stage_name"] == "clarifier:revise"


@pytest.mark.asyncio
async def test_revise_clarified_prompt_falls_back_when_model_returns_no_clarified_prompt():
    with patch(
        "adp.engine.clarifier.call_cloud_async",
        new=AsyncMock(return_value='JSON: {"question": "wrong shape"}'),
    ):
        result = await revise_clarified_prompt_async(
            "Create an Express.js API in books_api",
            "Include CRUD routes for books.",
        )

    assert result == "Create an Express.js API in books_api. Additional requirement: Include CRUD routes for books."


@pytest.mark.asyncio
async def test_revise_clarified_prompt_rejects_apology_meta_output():
    with patch(
        "adp.engine.clarifier.call_cloud_async",
        new=AsyncMock(
            return_value='JSON: {"clarified_prompt": "I’m sorry, but I need the current clarified prompt and the user’s refinement in order to rewrite it. Could you please provide those details?"}'
        ),
    ):
        result = await revise_clarified_prompt_async(
            "create a book management api with roles, in node.js using express.js. write the files under a new directory.",
            "under api/ dir",
        )

    assert result == (
        "create a book management api with roles, in node.js using express.js. "
        "write the files under a new directory. Additional requirement: under api/ dir"
    )


@pytest.mark.asyncio
async def test_clarifier_detect_invalid_shape_falls_back_without_crashing():
    with patch(
        "adp.engine.clarifier.call_local_async",
        new=AsyncMock(return_value='JSON: {"question":"wrong shape"}'),
    ):
        result = await clarify_prompt_async(
            "Do the task",
            ask_user=AsyncMock(),
        )

    assert result is not None
    assert result.clarified_prompt == "Do the task"
    assert result.clarification_turns_used == 0
