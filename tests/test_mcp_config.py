"""Tests for MCP config loading."""
from __future__ import annotations

from adp.mcp.config import _expand_config_value, _expand_env_vars


def test_expand_env_vars_replaces_known_values(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    assert _expand_env_vars("${SERPAPI_API_KEY}") == "test-key"


def test_expand_env_vars_missing_value_becomes_empty(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    assert _expand_env_vars("--api-key=${SERPAPI_API_KEY}") == "--api-key="


def test_expand_config_value_handles_nested_values(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    value = {
        "url": "https://mcp.serpapi.com/${SERPAPI_API_KEY}/mcp",
        "env": {"SERPAPI_API_KEY": "${SERPAPI_API_KEY}"},
    }

    assert _expand_config_value(value) == {
        "url": "https://mcp.serpapi.com/test-key/mcp",
        "env": {"SERPAPI_API_KEY": "test-key"},
    }


def test_expand_config_value_handles_streamable_http_url(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    assert (
        _expand_config_value("https://mcp.serpapi.com/${SERPAPI_API_KEY}/mcp")
        == "https://mcp.serpapi.com/test-key/mcp"
    )
