"""MCP server configuration loader.

Reads mcp_servers.toml from the project root or
~/.config/adp/mcp_servers.toml and returns a list of MCPServerConfig objects.
If no config file is found, returns an empty list (MCP silently disabled).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from adp.config import MCP_CONFIG_PATHS


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server connection."""

    name: str
    transport: str                          # "stdio" | "sse"

    # stdio transport fields
    command: str = ""                       # executable, e.g. "npx" or "uvx"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    # sse transport fields
    url: str = ""                           # e.g. "http://localhost:8080/sse"


def load_mcp_config() -> list[MCPServerConfig]:
    """
    Find and parse the first available mcp_servers.toml file.

    Returns an empty list if:
    - No config file is found (MCP silently disabled)
    - The config file exists but contains no [[servers]] entries
    """
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomllib  # type: ignore[import]
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore[import,no-redef]
            except ImportError:
                # Neither available — MCP config disabled
                return []

    for path in MCP_CONFIG_PATHS:
        if os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    data = tomllib.load(f)
            except Exception:
                return []

            servers = data.get("servers", [])
            result: list[MCPServerConfig] = []
            for s in servers:
                result.append(MCPServerConfig(
                    name=s.get("name", ""),
                    transport=s.get("transport", "stdio"),
                    command=s.get("command", ""),
                    args=s.get("args", []),
                    env=s.get("env", {}),
                    url=s.get("url", ""),
                ))
            return result

    return []  # No config file found — MCP disabled
