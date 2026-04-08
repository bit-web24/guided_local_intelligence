"""Persistent run-state storage for resumable agent execution."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from adp.config import (
    RUN_STATE_CONTEXT_PREVIEW_CHARS,
    RUN_STATE_DIRNAME,
    RUN_STATE_INLINE_CONTEXT_MAX_CHARS,
)
from adp.models.task import AnchorType, ContextDict, MicroTask, StageList, TaskPlan, TaskStatus


def generate_run_id() -> str:
    """Return a short unique identifier for a pipeline run."""
    return uuid4().hex[:8]


def get_run_dir(output_dir: str, run_id: str) -> Path:
    """Return the per-run storage directory under the output directory."""
    return Path(output_dir) / RUN_STATE_DIRNAME / run_id


def get_run_state_path(output_dir: str, run_id: str) -> Path:
    """Return the JSON checkpoint path for a run."""
    return get_run_dir(output_dir, run_id) / "state.json"


def get_run_context_path(output_dir: str, run_id: str) -> Path:
    """Return the optional spilled context path for large contexts."""
    return get_run_dir(output_dir, run_id) / "context.json"


def save_run_state(
    *,
    output_dir: str,
    run_id: str,
    user_prompt: str,
    plan: TaskPlan | None,
    context: ContextDict,
    files: dict[str, str],
    status: str,
    completed_stages: StageList,
    replan_count: int,
    max_replans: int,
    last_error: str | None = None,
) -> str:
    """Persist the current agent state to disk."""
    run_dir = get_run_dir(output_dir, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    path = get_run_state_path(output_dir, run_id)
    serialized_context = json.dumps(context, ensure_ascii=False)
    context_spilled = len(serialized_context) > RUN_STATE_INLINE_CONTEXT_MAX_CHARS
    persisted_context: dict[str, str]
    if context_spilled:
        context_path = get_run_context_path(output_dir, run_id)
        context_path.write_text(serialized_context, encoding="utf-8")
        persisted_context = _preview_context(context)
    else:
        context_path = get_run_context_path(output_dir, run_id)
        if context_path.exists():
            context_path.unlink()
        persisted_context = dict(context)

    payload = {
        "run_id": run_id,
        "user_prompt": user_prompt,
        "status": status,
        "completed_stages": list(completed_stages),
        "replan_count": replan_count,
        "max_replans": max_replans,
        "last_error": last_error,
        "updated_at": datetime.now().isoformat(),
        "plan": _plan_to_dict(plan) if plan is not None else None,
        "context": persisted_context,
        "context_spilled": context_spilled,
        "files": dict(files),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)


def load_run_state(output_dir: str, run_id: str) -> dict:
    """Load a persisted run state from disk."""
    path = get_run_state_path(output_dir, run_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("plan") is not None:
        data["plan"] = _plan_from_dict(data["plan"])
    if data.get("context_spilled"):
        context_path = get_run_context_path(output_dir, run_id)
        data["context"] = dict(json.loads(context_path.read_text(encoding="utf-8")))
    else:
        data["context"] = dict(data.get("context", {}))
    data["files"] = dict(data.get("files", {}))
    data["completed_stages"] = list(data.get("completed_stages", []))
    return data


def _preview_context(context: ContextDict) -> dict[str, str]:
    """Build a compact context preview for state.json when full context is spilled."""
    preview: dict[str, str] = {}
    for key, value in context.items():
        text = str(value)
        if len(text) <= RUN_STATE_CONTEXT_PREVIEW_CHARS:
            preview[key] = text
        else:
            preview[key] = f"{text[:RUN_STATE_CONTEXT_PREVIEW_CHARS]}... [truncated]"
    return preview


def _task_to_dict(task: MicroTask) -> dict:
    data = asdict(task)
    data["anchor"] = task.anchor.value
    data["status"] = task.status.value
    return data


def _task_from_dict(data: dict) -> MicroTask:
    return MicroTask(
        id=data["id"],
        description=data["description"],
        system_prompt_template=data["system_prompt_template"],
        input_text=data["input_text"],
        output_key=data["output_key"],
        depends_on=list(data.get("depends_on", [])),
        anchor=AnchorType(data["anchor"]),
        parallel_group=int(data["parallel_group"]),
        model_type=data.get("model_type", "coder"),
        mcp_tools=list(data.get("mcp_tools", [])),
        mcp_tool_args=dict(data.get("mcp_tool_args", {})),
        status=TaskStatus(data.get("status", TaskStatus.PENDING.value)),
        output=data.get("output"),
        retries=int(data.get("retries", 0)),
        error=data.get("error"),
    )


def _plan_to_dict(plan: TaskPlan) -> dict:
    return {
        "tasks": [_task_to_dict(task) for task in plan.tasks],
        "final_output_keys": list(plan.final_output_keys),
        "output_filenames": list(plan.output_filenames),
        "write_to_file": plan.write_to_file,
    }


def _plan_from_dict(data: dict) -> TaskPlan:
    return TaskPlan(
        tasks=[_task_from_dict(task) for task in data["tasks"]],
        final_output_keys=list(data["final_output_keys"]),
        output_filenames=list(data.get("output_filenames", [])),
        write_to_file=bool(data.get("write_to_file", True)),
    )
