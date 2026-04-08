"""Tests for resolve_tool_args()."""
from __future__ import annotations

import pytest
from adp.mcp.registry import MCPTool
from adp.mcp.resolver import resolve_tool_args, _fill_placeholders
from adp.models.task import AnchorType, MicroTask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(mcp_tools=None, mcp_tool_args=None) -> MicroTask:
    return MicroTask(
        id="t1",
        description="test task",
        system_prompt_template="EXAMPLES:\nOutput:",
        input_text="hello",
        output_key="result",
        depends_on=[],
        anchor=AnchorType.OUTPUT,
        parallel_group=0,
        mcp_tools=mcp_tools or [],
        mcp_tool_args=mcp_tool_args or {},
    )


def _make_tool(name: str, required: list[str], optional: list[str] = None) -> MCPTool:
    props = {k: {"type": "string"} for k in required + (optional or [])}
    return MCPTool(
        name=name,
        description="test tool",
        input_schema={"properties": props, "required": required},
        server_name="test_server",
    )


# ---------------------------------------------------------------------------
# _fill_placeholders
# ---------------------------------------------------------------------------

def test_fill_placeholders_basic():
    result = _fill_placeholders("Read {path}", {"path": "/tmp/foo.py"})
    assert result == "Read /tmp/foo.py"


def test_fill_placeholders_unknown_left_unchanged():
    result = _fill_placeholders("{unknown}", {})
    assert result == "{unknown}"


def test_fill_placeholders_multiple():
    result = _fill_placeholders("{a} and {b}", {"a": "X", "b": "Y"})
    assert result == "X and Y"


# ---------------------------------------------------------------------------
# resolve_tool_args
# ---------------------------------------------------------------------------

def test_auto_fill_from_context():
    """Required args present in context are auto-filled."""
    tool = _make_tool("read_file", required=["path"])
    task = _make_task(mcp_tools=["read_file"])
    context = {"path": "/home/user/main.py"}

    args = resolve_tool_args(tool, task, context)
    assert args["path"] == "/home/user/main.py"


def test_literal_overrides_context():
    """mcp_tool_args literal values override context auto-fill."""
    tool = _make_tool("read_file", required=["path"])
    task = _make_task(
        mcp_tools=["read_file"],
        mcp_tool_args={"read_file": {"path": "/explicit/path.py"}},
    )
    context = {"path": "/context/path.py"}

    args = resolve_tool_args(tool, task, context)
    assert args["path"] == "/explicit/path.py"


def test_placeholder_in_literal_override():
    """Placeholders ({key}) in literal overrides are resolved against context."""
    tool = _make_tool("read_file", required=["path"])
    task = _make_task(
        mcp_tools=["read_file"],
        mcp_tool_args={"read_file": {"path": "{output_dir}/main.py"}},
    )
    context = {"output_dir": "/home/user/out"}

    args = resolve_tool_args(tool, task, context)
    assert args["path"] == "/home/user/out/main.py"


def test_missing_required_raises():
    """Missing required args that can't be resolved raise ValueError."""
    tool = _make_tool("read_file", required=["path"])
    task = _make_task(mcp_tools=["read_file"])
    context = {}   # no 'path' anywhere

    with pytest.raises(ValueError, match="missing required arguments"):
        resolve_tool_args(tool, task, context)


def test_optional_args_not_required():
    """Optional (non-required) args don't cause errors when absent."""
    tool = _make_tool("search_docs", required=["query"], optional=["limit"])
    task = _make_task(
        mcp_tools=["search_docs"],
        mcp_tool_args={"search_docs": {"query": "FastAPI tutorial"}},
    )
    context = {}

    args = resolve_tool_args(tool, task, context)
    assert args["query"] == "FastAPI tutorial"
    assert "limit" not in args     # optional, not provided, not an error


def test_normalizes_accidental_wrapped_quotes_in_string_args():
    tool = _make_tool("search", required=["query"])
    task = _make_task(
        mcp_tools=["search"],
        mcp_tool_args={"search": {"query": "{q}"}},
    )
    context = {"q": '"current date and year"'}

    args = resolve_tool_args(tool, task, context)
    assert args["query"] == "current date and year"
