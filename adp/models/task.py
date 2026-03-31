from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"  # skipped because a dependency failed


class AnchorType(Enum):
    JSON = "JSON:"
    CODE = "Code:"
    OUTPUT = "Output:"
    MARKDOWN = "Markdown:"
    TOML = "TOML:"


@dataclass
class MicroTask:
    id: str                          # "t1", "t2", etc. — unique, short
    description: str                 # human-readable, shown in TUI task list
    system_prompt_template: str      # contains {placeholders} for context injection
    input_text: str                  # the actual input text for the local model
    output_key: str                  # key written to context dict on completion
    depends_on: list[str]            # list of task ids this task depends on
    anchor: AnchorType               # token ending the prompt; signals output start
    parallel_group: int              # tasks with same group number run concurrently
    model_type: str = field(default="coder")    # "coder" or "general"
    # MCP integration — assigned by the Decomposer, executed by the Executor
    # before the local model call. Results are injected as {tool_name}_result.
    mcp_tools: list[str] = field(default_factory=list)       # tool names to call
    mcp_tool_args: dict[str, dict] = field(default_factory=dict)  # tool → arg overrides
    # Runtime state
    status: TaskStatus = field(default=TaskStatus.PENDING)
    output: str | None = field(default=None)    # populated after successful execution
    retries: int = field(default=0)             # counts retry attempts
    error: str | None = field(default=None)     # populated if status == FAILED


@dataclass
class TaskPlan:
    tasks: list[MicroTask]
    final_output_keys: list[str]     # which context keys the assembler receives
    output_filenames: list[str]      # expected output filenames (for TUI display)
    write_to_file: bool = True     # True = files, False = single text response


# ContextDict: task output_key → task output value (plain string, already validated)
ContextDict = dict[str, str]


@dataclass
class PipelineResult:
    files: dict[str, str]            # filename → complete file content
    context: ContextDict             # full context dict for debugging
    tasks: list[MicroTask]           # final task list with all statuses and outputs
