"""FunctionGemma-backed MCP tool routing for executor prefetch."""
from __future__ import annotations

import json
from dataclasses import dataclass

from adp.config import get_model_config
from adp.engine.local_client import call_local_async, is_local_model_available
from adp.engine.validator import extract_after_anchor, validate
from adp.mcp.registry import MCPTool, ToolRegistry
from adp.models.task import AnchorType, ContextDict, MicroTask


TOOL_ROUTER_SYSTEM_PROMPT = """\
You are a function-calling tool router for an MCP-based local agent.
Choose tool calls ONLY from the candidate tools provided.
Return ONLY JSON with this exact shape:
{"calls":[{"tool":"tool_name","arguments":{"arg":"value"}}]}

Rules:
1. Only use candidate tool names exactly as given.
2. Include all required arguments for every returned tool call.
3. Prefer concrete literal argument values over placeholders when possible.
4. If planner defaults already look correct, you may keep them.
5. Do not invent tools, arguments, or prose.
6. Return a "calls" array. It may be empty if the planner defaults should be used as-is.

EXAMPLES:
Task:
- description: Read package metadata
- input: inspect pyproject.toml
Candidate tools:
- read_text_file(path) — Read a text file
Planner defaults:
{"read_text_file":{"path":"/repo/pyproject.toml"}}
JSON: {"calls":[{"tool":"read_text_file","arguments":{"path":"/repo/pyproject.toml"}}]}

Task:
- description: Search the web for quantization in llms
- input: gather sources
Candidate tools:
- web_search(query) — Search the web
Planner defaults:
{"web_search":{"query":"Quantization in LLMs"}}
JSON: {"calls":[{"tool":"web_search","arguments":{"query":"Quantization in LLMs"}}]}

Task:
- description: Fix config by reading two files
- input: inspect package and app config
Candidate tools:
- read_text_file(path) — Read a text file
- list_directory(path) — List a directory
Planner defaults:
{"list_directory":{"path":"/repo/app"},"read_text_file":{"path":"/repo/pyproject.toml"}}
JSON: {"calls":[{"tool":"list_directory","arguments":{"path":"/repo/app"}},{"tool":"read_text_file","arguments":{"path":"/repo/pyproject.toml"}}]}
"""


@dataclass(frozen=True)
class RoutedToolCall:
    tool: str
    arguments: dict


_ROUTER_MAX_CONTEXT_KEYS = 24
_ROUTER_MAX_ATTEMPTS = 2


def _truncate(value: str, limit: int = 400) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def _format_context(task: MicroTask, context: ContextDict) -> str:
    relevant_keys = list(dict.fromkeys([task.output_key] + list(context.keys())))
    relevant_keys = relevant_keys[:_ROUTER_MAX_CONTEXT_KEYS]
    lines: list[str] = []
    for key in relevant_keys:
        if key not in context:
            continue
        lines.append(f"- {key}: {_truncate(str(context[key]))}")
    return "\n".join(lines) if lines else "- none"


def _format_candidate_tools(task: MicroTask, tool_registry: ToolRegistry) -> str:
    lines: list[str] = []
    for tool_name in task.mcp_tools:
        tool = tool_registry.get(tool_name)
        if tool is None:
            continue
        props = tool.input_schema.get("properties", {})
        required = set(tool.input_schema.get("required", []))
        arg_parts = [
            f"{name}{'' if name in required else '?'}"
            for name in props
        ]
        lines.append(f"- {tool.name}({', '.join(arg_parts)}) — {tool.description}")
    return "\n".join(lines) if lines else "- none"


def _planner_defaults(task: MicroTask) -> str:
    return json.dumps(task.mcp_tool_args, indent=2, sort_keys=True)


async def route_task_tools(
    task: MicroTask,
    context: ContextDict,
    tool_registry: ToolRegistry,
) -> list[RoutedToolCall] | None:
    """Ask FunctionGemma to choose/repair tool calls for the task."""
    if not task.mcp_tools:
        return None

    task_context = _format_context(task, context)
    tool_text = _format_candidate_tools(task, tool_registry)
    model_name = get_model_config().local_tool_router
    if not await is_local_model_available(model_name):
        return None
    system_prompt = (
        f"{TOOL_ROUTER_SYSTEM_PROMPT}\n\n"
        f"Task description:\n{task.description}\n\n"
        f"Task input:\n{task.input_text}\n\n"
        f"Current context:\n{task_context}\n\n"
        f"Candidate tools:\n{tool_text}\n\n"
        f"Planner defaults:\n{_planner_defaults(task)}\n"
    )

    data: dict | None = None
    prompt_input = "Return tool call JSON only."
    for _attempt in range(_ROUTER_MAX_ATTEMPTS):
        try:
            raw = await call_local_async(
                system_prompt=system_prompt,
                input_text=prompt_input,
                anchor_str=AnchorType.JSON.value,
                model_name=model_name,
                stage_name="tool_router",
            )
            extracted = extract_after_anchor(raw, AnchorType.JSON)
            is_valid, cleaned = validate(extracted, AnchorType.JSON)
            if not is_valid:
                prompt_input = (
                    "Your last output was invalid JSON. Return ONLY "
                    '{"calls":[{"tool":"name","arguments":{...}}]}.'
                )
                continue
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and isinstance(parsed.get("calls"), list):
                data = parsed
                break
            prompt_input = (
                "Your last output missed the calls array. Return ONLY "
                '{"calls":[{"tool":"name","arguments":{...}}]}.'
            )
        except Exception:
            return None
    if data is None:
        return None
    calls = data.get("calls", [])

    routed_calls: list[RoutedToolCall] = []
    seen_tools: set[str] = set()
    for entry in calls:
        if not isinstance(entry, dict):
            continue
        tool_name = entry.get("tool")
        arguments = entry.get("arguments", {})
        if (
            not isinstance(tool_name, str)
            or tool_name not in task.mcp_tools
            or tool_name in seen_tools
            or not isinstance(arguments, dict)
        ):
            continue
        tool = tool_registry.get(tool_name)
        if tool is None:
            continue
        # Merge FunctionGemma output with planner defaults to keep required args.
        merged_args = dict(task.mcp_tool_args.get(tool_name, {}))
        merged_args.update(arguments)
        required = set(tool.input_schema.get("required", []))
        if any(req not in merged_args for req in required):
            continue
        seen_tools.add(tool_name)
        routed_calls.append(RoutedToolCall(tool=tool_name, arguments=merged_args))

    return routed_calls or None
