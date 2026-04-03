"""Tests for MCP pre-fetch integration in the executor.

Since MCP pre-fetch now lives in _prefetch_mcp_for_group() (called from
execute_plan() in the main task, before asyncio.gather()), tests target
that function directly rather than execute_task().
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from adp.models.task import AnchorType, MicroTask, TaskPlan, TaskStatus
from adp.stages.executor import _prefetch_mcp_for_group, execute_task, fill_template
from adp.mcp.registry import MCPTool, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(mcp_tools=None, mcp_tool_args=None) -> MicroTask:
    return MicroTask(
        id="t1",
        description="test",
        system_prompt_template=(
            "EXAMPLES:\n"
            "Input: foo\n"
            "Output: bar\n"
            "---\n"
            "File content: {read_file_result}\n"
            "Input: {input}\n"
            "Output:"
        ),
        input_text="write a docstring",
        output_key="docstring",
        depends_on=[],
        anchor=AnchorType.OUTPUT,
        parallel_group=0,
        mcp_tools=mcp_tools or [],
        mcp_tool_args=mcp_tool_args or {},
    )


def _make_registry(tool: MCPTool) -> ToolRegistry:
    return ToolRegistry({tool.name: tool})


def _make_tool() -> MCPTool:
    return MCPTool(
        name="read_file",
        description="Read a file",
        input_schema={"properties": {"path": {"type": "string"}}, "required": ["path"]},
        server_name="filesystem",
    )


# ---------------------------------------------------------------------------
# _prefetch_mcp_for_group — the main pre-fetch function
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_result_injected_into_context():
    """
    Tool result should be written to context as 'read_file_result'
    by _prefetch_mcp_for_group, before the local model is called.
    """
    task = _make_task(
        mcp_tools=["read_file"],
        mcp_tool_args={"read_file": {"path": "/tmp/main.py"}},
    )
    tool = _make_tool()
    registry = _make_registry(tool)

    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "def foo(): pass"

    context = {}
    await _prefetch_mcp_for_group([task], context, mcp_manager, registry)

    mcp_manager.call_tool.assert_awaited_once_with("read_file", {"path": "/tmp/main.py"})
    assert "t1_read_file_result" in context
    assert context["t1_read_file_result"] == "def foo(): pass"


@pytest.mark.asyncio
async def test_mcp_callbacks_report_tool_start_and_success():
    task = _make_task(
        mcp_tools=["read_file"],
        mcp_tool_args={"read_file": {"path": "/tmp/main.py"}},
    )
    tool = _make_tool()
    registry = _make_registry(tool)

    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "def foo(): pass"

    started: list[tuple[str, str]] = []
    finished: list[tuple[str, str, bool, str | None]] = []

    context = {}
    await _prefetch_mcp_for_group(
        [task],
        context,
        mcp_manager,
        registry,
        on_tool_start=lambda task, tool_name: started.append((task.id, tool_name)),
        on_tool_done=lambda task, tool_name, ok, detail: finished.append(
            (task.id, tool_name, ok, detail)
        ),
    )

    assert started == [("t1", "read_file")]
    assert finished == [("t1", "read_file", True, None)]


@pytest.mark.asyncio
async def test_mcp_failure_writes_error_notice():
    """
    A failing MCP tool call should not crash the pipeline.
    It should write an error notice to context.
    """
    task = _make_task(
        mcp_tools=["read_file"],
        mcp_tool_args={"read_file": {"path": "/tmp/missing.py"}},
    )
    tool = _make_tool()
    registry = _make_registry(tool)

    mcp_manager = AsyncMock()
    mcp_manager.call_tool.side_effect = Exception("File not found")

    context = {}
    await _prefetch_mcp_for_group([task], context, mcp_manager, registry)

    assert "t1_read_file_result" in context
    assert "failed" in context["t1_read_file_result"].lower()


@pytest.mark.asyncio
async def test_mcp_callbacks_report_tool_failure():
    task = _make_task(
        mcp_tools=["read_file"],
        mcp_tool_args={"read_file": {"path": "/tmp/missing.py"}},
    )
    tool = _make_tool()
    registry = _make_registry(tool)

    mcp_manager = AsyncMock()
    mcp_manager.call_tool.side_effect = Exception("File not found")

    started: list[tuple[str, str]] = []
    finished: list[tuple[str, str, bool, str | None]] = []

    context = {}
    await _prefetch_mcp_for_group(
        [task],
        context,
        mcp_manager,
        registry,
        on_tool_start=lambda task, tool_name: started.append((task.id, tool_name)),
        on_tool_done=lambda task, tool_name, ok, detail: finished.append(
            (task.id, tool_name, ok, detail)
        ),
    )

    assert started == [("t1", "read_file")]
    assert finished == [("t1", "read_file", False, "File not found")]


@pytest.mark.asyncio
async def test_shared_tool_fetched_only_once():
    """
    If two tasks in the same group use the same tool, it should be
    fetched only once (the second task finds the key already in context).
    """
    task1 = _make_task(
        mcp_tools=["read_file"],
        mcp_tool_args={"read_file": {"path": "/tmp/main.py"}},
    )
    task2 = _make_task(
        mcp_tools=["read_file"],
        mcp_tool_args={"read_file": {"path": "/tmp/main.py"}},
    )
    task2.id = "t2"

    tool = _make_tool()
    registry = _make_registry(tool)

    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "def foo(): pass"

    context = {}
    await _prefetch_mcp_for_group([task1, task2], context, mcp_manager, registry)

    # Called only once: t1 fetches, t2 has its OWN key so also fetches
    # With task-scoped keys, both tasks always fetch independently
    assert mcp_manager.call_tool.await_count == 2
    assert "t1_read_file_result" in context
    assert "t2_read_file_result" in context


@pytest.mark.asyncio
async def test_unknown_tool_writes_not_found_notice():
    """Tools the Decomposer invented that aren't in the registry get an error notice."""
    task = _make_task(mcp_tools=["nonexistent_tool"])
    registry = ToolRegistry()   # empty

    mcp_manager = AsyncMock()
    context = {}
    await _prefetch_mcp_for_group([task], context, mcp_manager, registry)

    assert "t1_nonexistent_tool_result" in context
    assert "not found" in context["t1_nonexistent_tool_result"].lower()
    mcp_manager.call_tool.assert_not_awaited()


# ---------------------------------------------------------------------------
# execute_task — now local-model-only, no MCP args
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_task_uses_prefetched_context():
    """
    execute_task() reads MCP results already in context (put there by
    _prefetch_mcp_for_group), not from mcp_manager directly.
    """
    task = _make_task(mcp_tools=["read_file"])
    context = {"t1_read_file_result": "def foo(): pass"}   # pre-filled with task-scoped key

    on_start = MagicMock()
    on_done = MagicMock()
    on_failed = MagicMock()

    with patch("adp.stages.executor.call_local_async", new_callable=AsyncMock) as mock_local:
        mock_local.return_value = "Output: A docstring for foo."
        with patch("adp.stages.executor.validate", return_value=(True, "A docstring for foo.")):
            with patch("adp.stages.executor.extract_after_anchor", return_value="A docstring for foo."):
                await execute_task(task, context, on_start, on_done, on_failed)

    assert task.status == TaskStatus.DONE
    assert "t1_read_file_result" in context   # still there, not removed


# ---------------------------------------------------------------------------
# fill_template (existing, but verify MCP key placeholder resolves)
# ---------------------------------------------------------------------------

def test_fill_template_with_mcp_result_key():
    template = "Context: {t2_read_file_result}\nOutput:"
    context = {"t2_read_file_result": "def foo(): pass"}
    result = fill_template(template, context)
    assert "def foo(): pass" in result
