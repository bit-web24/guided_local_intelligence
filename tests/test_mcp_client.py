"""Tests for MCP client tool-call behavior."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from adp.mcp.client import MCPClientManager, _prepare_filesystem_server_roots
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
                    '"partialFailures":[{"message":"Search provider returned a verification page"}]}'
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


@pytest.mark.asyncio
async def test_call_tool_raises_on_zero_search_results_without_partial_failures(monkeypatch):
    manager = _manager_for_tool("search")
    manager._make_transport = lambda *args, **kwargs: _DummyTransport()  # type: ignore[assignment]
    _DummySession.response = SimpleNamespace(
        content=[
            SimpleNamespace(
                text='{"query":"q","totalResults":0,"results":[],"partialFailures":[]}'
            )
        ],
        isError=False,
    )
    monkeypatch.setattr("mcp.ClientSession", _DummySession)

    with patch("adp.mcp.client.append_tool_call_log") as log_mock:
        with pytest.raises(RuntimeError, match="no results"):
            await manager.call_tool("search", {"query": "q"})

    log_mock.assert_called_once()


@pytest.mark.asyncio
async def test_call_tool_rejects_unresolved_search_query_placeholder():
    manager = _manager_for_tool("search")

    with patch("adp.mcp.client.append_tool_call_log") as log_mock:
        with pytest.raises(RuntimeError, match="unresolved query placeholder"):
            await manager.call_tool("search", {"query": "{search_args.query}"})

    log_mock.assert_called_once()


def test_prepare_filesystem_server_roots_creates_missing_directories(tmp_path):
    root_path = tmp_path / "adp_output"
    cfg = MCPServerConfig(
        name="filesystem",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(root_path)],
    )

    assert not root_path.exists()
    _prepare_filesystem_server_roots(cfg)
    assert root_path.exists()


def test_make_transport_supports_streamable_http():
    manager = MCPClientManager()
    cfg = MCPServerConfig(
        name="serpapi",
        transport="streamable_http",
        url="https://mcp.serpapi.com/test-key/mcp",
        headers={"Authorization": "Bearer test-key"},
    )
    calls = []

    def fake_streamablehttp_client(url, headers=None):
        calls.append((url, headers))
        return object()

    transport = manager._make_transport(
        cfg,
        StdioServerParameters=None,
        stdio_client=None,
        sse_client=None,
        streamablehttp_client=fake_streamablehttp_client,
    )

    assert transport is not None
    assert calls == [
        (
            "https://mcp.serpapi.com/test-key/mcp",
            {"Authorization": "Bearer test-key"},
        )
    ]
