"""Tests for ToolRegistry."""
from __future__ import annotations

import pytest
from adp.mcp.registry import MCPTool, ToolRegistry, _format_args


# ---------------------------------------------------------------------------
# _format_args
# ---------------------------------------------------------------------------

def test_format_args_all_required():
    schema = {
        "properties": {"path": {}, "encoding": {}},
        "required": ["path", "encoding"],
    }
    result = _format_args(schema)
    assert "path" in result
    assert "encoding" in result
    assert "?" not in result        # both required = no question marks


def test_format_args_optional():
    schema = {
        "properties": {"path": {}, "limit": {}},
        "required": ["path"],
    }
    result = _format_args(schema)
    assert "path" in result
    assert "limit?" in result       # optional field has '?'


def test_format_args_empty_schema():
    assert _format_args({}) == ""


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

def _make_registry(*tool_specs) -> ToolRegistry:
    tools = {}
    for name, description, schema in tool_specs:
        tools[name] = MCPTool(
            name=name,
            description=description,
            input_schema=schema,
            server_name="test_server",
        )
    return ToolRegistry(tools)


def test_registry_is_empty():
    assert ToolRegistry().is_empty()
    r = _make_registry(("read_file", "Read a file", {"properties": {"path": {}}, "required": ["path"]}))
    assert not r.is_empty()


def test_registry_contains():
    r = _make_registry(("read_file", "Read a file", {}))
    assert "read_file" in r
    assert "write_file" not in r


def test_registry_get():
    r = _make_registry(("read_file", "Read a file", {}))
    assert r.get("read_file") is not None
    assert r.get("missing") is None


def test_tool_summary_format():
    r = _make_registry(
        ("read_file", "Read a file from the filesystem", {
            "properties": {"path": {}},
            "required": ["path"],
        }),
        ("search_docs", "Search the documentation index", {
            "properties": {"query": {}, "limit": {}},
            "required": ["query"],
        }),
    )
    summary = r.tool_summary_for_decomposer()
    assert "read_file(path)" in summary
    assert "Read a file from the filesystem" in summary
    assert "search_docs(query, limit?)" in summary
    assert "Search the documentation index" in summary


def test_tool_summary_empty_registry():
    assert ToolRegistry().tool_summary_for_decomposer() == ""
