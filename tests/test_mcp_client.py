"""Tests for MCP client tool-call behavior."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from adp.mcp.client import MCPClientManager
from adp.mcp.config import MCPServerConfig


class _DummyTransport:
    async def __aenter__(self):
        return (object(), object())

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummySession:
    response = None

    def __init__(self, _read, _write):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def initialize(self):
        return None

    async def call_tool(self, _tool_name, arguments):
        assert isinstance(arguments, dict)
        return self.response


def _manager_for_tool(tool_name: str = "search") -> MCPClientManager:
    manager = MCPClientManager()
    manager._tool_server[tool_name] = MCPServerConfig(
        name="test",
        transport="stdio",
        command="noop",
        args=[],
        env={},
    )
    return manager


@pytest.mark.asyncio
async def test_call_tool_logs_successful_output(monkeypatch):
    manager = _manager_for_tool("read_file")
    manager._make_transport = lambda *args, **kwargs: _DummyTransport()  # type: ignore[assignment]
    _DummySession.response = SimpleNamespace(
        content=[SimpleNamespace(text="file content")],
        isError=False,
    )
    monkeypatch.setattr("mcp.ClientSession", _DummySession)

    with patch("adp.mcp.client.append_tool_call_log") as log_mock:
        result = await manager.call_tool("read_file", {"path": "/tmp/a.py"})

    assert result == "file content"
    log_mock.assert_called_once_with(
        tool_name="read_file",
        arguments={"path": "/tmp/a.py"},
        output="file content",
    )


@pytest.mark.asyncio
async def test_call_tool_raises_when_response_is_error(monkeypatch):
    manager = _manager_for_tool("write_file")
    manager._make_transport = lambda *args, **kwargs: _DummyTransport()  # type: ignore[assignment]
    _DummySession.response = SimpleNamespace(
        content=[SimpleNamespace(text="Access denied")],
        isError=True,
    )
    monkeypatch.setattr("mcp.ClientSession", _DummySession)

    with patch("adp.mcp.client.append_tool_call_log") as log_mock:
        with pytest.raises(RuntimeError, match="Access denied"):
            await manager.call_tool("write_file", {"path": "/tmp/a.py", "content": "x"})

    log_mock.assert_called_once_with(
        tool_name="write_file",
        arguments={"path": "/tmp/a.py", "content": "x"},
        error="Access denied",
    )


@pytest.mark.asyncio
async def test_call_tool_raises_on_semantic_search_failure(monkeypatch):
    manager = _manager_for_tool("search")
    manager._make_transport = lambda *args, **kwargs: _DummyTransport()  # type: ignore[assignment]
    _DummySession.response = SimpleNamespace(
        content=[
            SimpleNamespace(
                text=(
                    '{"query":"q","totalResults":0,"results":[],'
                    '"partialFailures":[{"message":"Startpage returned a verification page"}]}'
                )
            )
        ],
        isError=False,
    )
    monkeypatch.setattr("mcp.ClientSession", _DummySession)

    with patch("adp.mcp.client.append_tool_call_log") as log_mock:
        with pytest.raises(RuntimeError, match="Search failed"):
            await manager.call_tool("search", {"query": "q"})

    log_mock.assert_called_once()
    kwargs = log_mock.call_args.kwargs
    assert kwargs["tool_name"] == "search"
    assert kwargs["arguments"] == {"query": "q"}
    assert "Search failed" in kwargs["error"]
