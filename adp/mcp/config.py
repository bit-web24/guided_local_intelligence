"""MCP server configuration loader.

Reads mcp_servers.toml from the project root or
~/.config/adp/mcp_servers.toml and returns a list of MCPServerConfig objects.
If no config file is found, returns an empty list (MCP silently disabled).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
import re

from adp.config import MCP_CONFIG_PATHS


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server connection."""

    name: str
    transport: str                          # "stdio" | "sse" | "streamable_http"

    # stdio transport fields
    command: str = ""                       # executable, e.g. "npx" or "uvx"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    # sse transport fields
    url: str = ""                           # e.g. "http://localhost:8080/sse"
    headers: dict[str, str] = field(default_factory=dict)


_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env_vars(value: str) -> str:
    """Expand ${VAR_NAME} placeholders using the current process environment."""
    def replace(match: re.Match) -> str:
        return os.getenv(match.group(1), "")

    return _ENV_VAR_RE.sub(replace, value)


def _expand_config_value(value):
    """Recursively expand env placeholders in TOML config values."""
    if isinstance(value, str):
        return _expand_env_vars(value)
    if isinstance(value, list):
        return [_expand_config_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _expand_config_value(item)
            for key, item in value.items()
        }
    return value


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
                    command=_expand_config_value(s.get("command", "")),
                    args=_expand_config_value(s.get("args", [])),
                    env=_expand_config_value(s.get("env", {})),
                    url=_expand_config_value(s.get("url", "")),
                    headers=_expand_config_value(s.get("headers", {})),
                ))
            return result

    return []  # No config file found — MCP disabled
