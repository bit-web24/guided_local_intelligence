"""Tests for assembler model routing."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from adp.models.task import AnchorType, MicroTask, TaskPlan
from adp.stages.assembler import assemble


def _make_plan(*, write_to_file: bool) -> TaskPlan:
    task = MicroTask(
        id="t1",
        description="Task t1",
        system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
        input_text="run",
        output_key="answer",
        depends_on=[],
        anchor=AnchorType.OUTPUT,
        parallel_group=0,
    )
    return TaskPlan(
        tasks=[task],
        final_output_keys=["answer"],
        output_filenames=["answer.txt"] if write_to_file else [],
        write_to_file=write_to_file,
    )


@pytest.mark.asyncio
async def test_text_assembly_uses_local_first():
    plan = _make_plan(write_to_file=False)

    with patch(
        "adp.stages.assembler.call_local_async",
        new=AsyncMock(return_value="Local assembled response"),
    ) as local_mock, patch(
        "adp.stages.assembler.call_cloud_async",
        new=AsyncMock(return_value="Cloud assembled response"),
    ) as cloud_mock:
        files = await assemble(plan, {"answer": "Final answer fragment"}, user_prompt="Answer the question")

    assert files == {"__stdout__": "Local assembled response"}
    assert local_mock.await_args.kwargs["stage_name"] == "assembler:local"
    cloud_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_assembly_falls_back_to_cloud():
    plan = _make_plan(write_to_file=False)

    with patch(
        "adp.stages.assembler.call_local_async",
        new=AsyncMock(side_effect=RuntimeError("local failed")),
    ), patch(
        "adp.stages.assembler.call_cloud_async",
        new=AsyncMock(return_value="Cloud assembled response"),
    ) as cloud_mock:
        files = await assemble(plan, {"answer": "Final answer fragment"}, user_prompt="Answer the question")

    assert files == {"__stdout__": "Cloud assembled response"}
    assert cloud_mock.await_args.kwargs["stage_name"] == "assembler"


@pytest.mark.asyncio
async def test_file_assembly_stays_on_cloud():
    plan = _make_plan(write_to_file=True)

    with patch(
        "adp.stages.assembler.call_local_async",
        new=AsyncMock(return_value="should not be used"),
    ) as local_mock, patch(
        "adp.stages.assembler.call_cloud_async",
        new=AsyncMock(
            return_value="--- FILE: answer.txt ---\nFull file content\n--- END FILE ---"
        ),
    ) as cloud_mock:
        files = await assemble(plan, {"answer": "Final answer fragment"}, user_prompt="Write a file")

    assert files == {"answer.txt": "Full file content"}
    local_mock.assert_not_awaited()
    assert cloud_mock.await_args.kwargs["stage_name"] == "assembler"
