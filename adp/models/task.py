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


class TaskKind(Enum):
    EXTRACT = "extract"
    CLASSIFY = "classify"
    TRANSFORM = "transform"
    CODEGEN = "codegen"
    CRITIC = "critic"
    REPAIR = "repair"
    SUMMARIZE = "summarize"


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
    task_kind: TaskKind = field(default=TaskKind.CODEGEN)
    validator_rule: str | None = field(default=None)
    max_output_chars: int | None = field(default=None)
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


@dataclass
class ValidationResult:
    ok: bool
    cleaned_output: str
    reason: str = ""


@dataclass
class EvaluationSummary:
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    success_rate: float
    retries: int
    by_kind: dict[str, dict[str, int]]


# ContextDict: task output_key → task output value (plain string, already validated)
ContextDict = dict[str, str]


@dataclass
class PipelineResult:
    files: dict[str, str]            # filename → complete file content
    context: ContextDict             # full context dict for debugging
    tasks: list[MicroTask]           # final task list with all statuses and outputs
