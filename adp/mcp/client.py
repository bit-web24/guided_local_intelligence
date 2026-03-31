"""MCPClientManager — per-call MCP connections with zero persistent tasks.

Architecture: Connect-Call-Disconnect per tool call
---------------------------------------------------
Earlier designs tried to keep ClientSession alive for the whole pipeline run.
This requires a long-lived background anyio task (_receive_loop) that must be
kept alive, cancelled cleanly, and whose cancel scope must never be crossed.
Under Python 3.14 + anyio 4.x, this causes:
    "Attempted to exit cancel scope in a different task than it was entered in"

The simplest fix: open a fresh transport + session for EACH tool call.
MCP server subprocess stays alive between calls (pipe stays open) but we
re-handshake the JSON-RPC session for each tool call.

This is slightly slower (one extra initialize() per call) but:
  - Zero persistent background tasks
  - Zero cross-task cancel scope issues
  - Trivial cleanup: nothing to cancel
  - Correct behaviour under all Python / anyio versions

For typical ADP workloads (2-5 tool calls per pipeline run, each taking
50-100ms) the overhead is negligible compared to local model inference time.
"""
from __future__ import annotations

import logging
from typing import Any

from adp.config import MCP_MAX_TOOL_RESULT_CHARS
from adp.mcp.config import MCPServerConfig
from adp.mcp.registry import MCPTool, ToolRegistry

logger = logging.getLogger(__name__)


class MCPClientManager:
    """
    Stateless MCP client. Opens a fresh session per tool call.

    start() connects once to discover the available tools, then disconnects.
    call_tool() opens a new session, calls the tool, and disconnects.

    Usage:
        async with MCPClientManager() as mgr:
            registry = await mgr.start(configs)
            result   = await mgr.call_tool("read_file", {"path": "main.py"})
        # Nothing to clean up — all connections are already closed
    """

    def __init__(self) -> None:
        self._configs: list[MCPServerConfig] = []
        self._registry: ToolRegistry = ToolRegistry()
        # Maps tool_name → server config that owns it
        self._tool_server: dict[str, MCPServerConfig] = {}

    # ------------------------------------------------------------------
    # Async context manager (trivial — no persistent state)
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "MCPClientManager":
        return self

    async def __aexit__(self, *exc_info) -> None:
        pass  # Nothing to clean up in stateless mode

    # ------------------------------------------------------------------
    # Start: discover tools from all servers
    # ------------------------------------------------------------------

    async def start(self, configs: list[MCPServerConfig]) -> ToolRegistry:
        """
        Connect to each server, discover its tools, then disconnect.
        Builds a ToolRegistry and an internal map of tool → server config.
        """
        if not configs:
            return ToolRegistry()

        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client
            from mcp.client.sse import sse_client
        except ImportError as e:
            logger.warning(f"mcp package not installed — MCP disabled. ({e})")
            return ToolRegistry()

        self._configs = configs
        all_tools: dict[str, MCPTool] = {}

        for cfg in configs:
            try:
                tools = await self._discover_tools(
                    cfg, StdioServerParameters, stdio_client, sse_client, ClientSession
                )
                for tool in tools:
                    all_tools[tool.name] = tool
                    self._tool_server[tool.name] = cfg
                logger.info(
                    f"MCP '{cfg.name}': {len(tools)} tools "
                    f"({[t.name for t in tools[:4]]}{'...' if len(tools) > 4 else ''})"
                )
            except Exception as e:
                logger.warning(f"MCP server '{cfg.name}' tool discovery failed: {e}")

        self._registry = ToolRegistry(all_tools)
        return self._registry

    async def _discover_tools(
        self,
        cfg: MCPServerConfig,
        StdioServerParameters,
        stdio_client,
        sse_client,
        ClientSession,
    ) -> list[MCPTool]:
        """Open a fresh session, list tools, close. Returns list[MCPTool]."""
        transport_cm = self._make_transport(
            cfg, StdioServerParameters, stdio_client, sse_client
        )
        async with transport_cm as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_response = await session.list_tools()
                return [
                    MCPTool(
                        name=t.name,
                        description=(t.description or "").split("\n")[0][:120],
                        input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
                        server_name=cfg.name,
                    )
                    for t in tools_response.tools
                ]

    # ------------------------------------------------------------------
    # Tool call: fresh session per call
    # ------------------------------------------------------------------

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        Open a fresh MCP session, call the tool, return result string.

        Each call is independent: no persistent background tasks, no shared
        cancel scopes, no cross-task state.
        """
        cfg = self._tool_server.get(tool_name)
        if cfg is None:
            raise KeyError(
                f"MCP tool '{tool_name}' is not registered. "
                f"Available: {list(self._tool_server.keys())}"
            )

        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client
            from mcp.client.sse import sse_client
        except ImportError as e:
            raise RuntimeError(f"mcp package not available: {e}") from e

        transport_cm = self._make_transport(
            cfg, StdioServerParameters, stdio_client, sse_client
        )
        async with transport_cm as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool(tool_name, arguments=arguments)

        parts: list[str] = []
        for item in response.content:
            parts.append(item.text if hasattr(item, "text") else str(item))
        raw = "\n".join(parts)

        if len(raw) > MCP_MAX_TOOL_RESULT_CHARS:
            raw = (
                raw[:MCP_MAX_TOOL_RESULT_CHARS]
                + f"\n... [truncated at {MCP_MAX_TOOL_RESULT_CHARS} chars]"
            )
        return raw

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_transport(
        self,
        cfg: MCPServerConfig,
        StdioServerParameters,
        stdio_client,
        sse_client,
    ):
        """Return the appropriate transport context manager for a server config."""
        if cfg.transport == "stdio":
            params = StdioServerParameters(
                command=cfg.command,
                args=list(cfg.args),
                env=cfg.env if cfg.env else None,
            )
            return stdio_client(params)
        elif cfg.transport == "sse":
            return sse_client(cfg.url)
        else:
            raise ValueError(
                f"Unknown transport '{cfg.transport}' for server '{cfg.name}'. "
                "Use 'stdio' or 'sse'."
            )
