"""MCP argument resolver.

resolve_tool_args() constructs the final argument dict for a tool call
by merging:
  1. Defaults / required fields inferred from the tool's JSON Schema
  2. Literal overrides from MicroTask.mcp_tool_args[tool_name]
  3. {placeholder} substitution against the current context dict

The local model never calls tools directly — this resolver is pure Python
glue that runs in the Executor before the local model call.
"""
from __future__ import annotations

import json
import re

from adp.mcp.registry import MCPTool
from adp.models.task import ContextDict, MicroTask


def resolve_tool_args(
    tool: MCPTool,
    task: MicroTask,
    context: ContextDict,
    explicit_overrides: dict | None = None,
) -> dict:
    """
    Build the final args dict to pass to MCPClientManager.call_tool().

    Resolution order (later overrides earlier):
    1. Empty dict (start)
    2. Required schema fields pre-filled from context if the key name
       matches a context key (e.g., tool arg "path" ← context["path"])
    3. Literal overrides from task.mcp_tool_args[tool.name]
    4. {placeholder} substitution on any string values using context

    Args:
        tool:    The MCPTool whose schema defines expected arguments.
        task:    The current MicroTask (contains mcp_tool_args overrides).
        context: The live context dict (upstream task outputs + tool results).

    Returns:
        A dict ready to be passed as the `arguments` kwarg to call_tool().
    """
    # Step 1: Start with tool's required properties auto-filled from context
    args: dict = {}
    props = tool.input_schema.get("properties", {})
    required = set(tool.input_schema.get("required", []))
    for arg_name in required:
        if arg_name in context:
            args[arg_name] = context[arg_name]

    # Step 2: Apply literal overrides from task.mcp_tool_args (if any)
    literal_overrides = task.mcp_tool_args.get(tool.name, {})
    args.update(literal_overrides)
    if explicit_overrides:
        args.update(explicit_overrides)

    # Step 3: Resolve {placeholder} patterns in all string values
    for key, value in args.items():
        if isinstance(value, str):
            resolved = _fill_placeholders(value, context)
            args[key] = _normalize_string_arg(resolved)

    # Step 4: Ensure all required args are present (raise early if missing)
    missing = [r for r in required if r not in args]
    if missing:
        raise ValueError(
            f"MCP tool '{tool.name}' called from task '{task.id}' is missing "
            f"required arguments: {missing}. "
            "Add them to mcp_tool_args in the task plan."
        )

    return args


def _fill_placeholders(template: str, context: ContextDict) -> str:
    """
    Replace {key} patterns in a string with values from context dict.
    Unknown placeholders are left unchanged.
    """
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        return context.get(key, m.group(0))   # leave unchanged if not found

    return re.sub(r"\{(\w+)\}", _replace, template)


def _normalize_string_arg(value: str) -> str:
    """Normalize string args that are accidental JSON-encoded strings."""
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        unquoted = text[1:-1].strip()
        if unquoted:
            return unquoted
    if text.startswith('"') and text.endswith('"'):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, str):
                return parsed.strip() or parsed
        except Exception:
            return text
    return text
