"""MCP tool registry.

ToolRegistry is the single authoritative map of tool name → MCPTool.
It is built by MCPClientManager.start() after connecting to all servers
and is passed to the Decomposer and Executor.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MCPTool:
    """Metadata for a single MCP tool exposed by a server."""

    name: str
    description: str        # 1-line; injected into the Decomposer system prompt
    input_schema: dict      # JSON Schema object describing the tool's arguments
    server_name: str        # which MCP server owns this tool


class ToolRegistry:
    """
    Immutable-ish map of tool name → MCPTool.

    Built once on startup; read-only during pipeline execution.
    """

    def __init__(self, tools: dict[str, MCPTool] | None = None) -> None:
        self._tools: dict[str, MCPTool] = tools or {}

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, name: str) -> MCPTool | None:
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __getitem__(self, name: str) -> MCPTool:
        return self._tools[name]

    def is_empty(self) -> bool:
        return len(self._tools) == 0

    def all_tools(self) -> list[MCPTool]:
        return list(self._tools.values())

    # ------------------------------------------------------------------
    # Decomposer integration
    # ------------------------------------------------------------------

    def tool_summary_for_decomposer(self) -> str:
        """
        Return a compact multi-line string listing each tool with its
        argument names and description. Injected into the Decomposer
        system prompt so it knows what tools are available.

        Example output:
            read_file(path) — Read a file from the filesystem
            list_directory(path) — List directory contents
            search_docs(query, limit?) — Search the documentation index
        """
        if self.is_empty():
            return ""

        lines: list[str] = []
        for tool in self._tools.values():
            args = _format_args(tool.input_schema)
            lines.append(f"{tool.name}({args}) — {tool.description}")
        return "\n".join(lines)


def _format_args(schema: dict) -> str:
    """
    Produce a brief arg list string from a JSON Schema, e.g.
    'path, encoding?' from {"path": {required}, "encoding": {not required}}.
    """
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    parts: list[str] = []
    for prop_name in props:
        if prop_name in required:
            parts.append(prop_name)
        else:
            parts.append(f"{prop_name}?")
    return ", ".join(parts) if parts else ""
