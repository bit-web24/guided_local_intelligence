"""File writer — writes assembled output files and run artifacts to disk."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from adp.models.task import ContextDict, TaskPlan
from adp.stages.executor import fill_template


def write_output_files(
    files: dict[str, str],
    output_dir: str,
) -> list[tuple[str, int]]:
    """
    Write all files to output_dir. Create directory tree as needed.

    Raises IOError if any file is written as 0 bytes (indicates silent failure).
    Returns list of (filename, byte_count) for TUI display.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    written: list[tuple[str, int]] = []
    for filename, content in files.items():
        file_path = Path(filename)
        if file_path.is_absolute() or ".." in file_path.parts:
            raise ValueError(
                f"Output filename '{filename}' must use relative paths within the output directory."
            )

        path = base / file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        size = path.stat().st_size
        if size == 0:
            raise IOError(
                f"File '{filename}' was written but is 0 bytes — "
                "this indicates the assembler returned empty content."
            )
        written.append((filename, size))

    return written

def write_execution_log(user_prompt: str, plan: TaskPlan, output_dir: str) -> None:
    """
    Writes a Markdown log of the execution details to the output directory.
    Includes the original prompt, final execution decisions, and micro-task summaries.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = out_dir / ".adp_execution_log.md"
    
    lines = [
        "# ADP Execution Log",
        "",
        "## User Prompt",
        f"```text\n{user_prompt}\n```",
        "",
        "## Output Strategy",
        f"- **Write to Files:** `{plan.write_to_file}`",
        f"- **Expected Files:** `{', '.join(plan.output_filenames) if plan.output_filenames else 'None'}`",
        "",
        "## Micro-Tasks",
    ]
    
    for task in plan.tasks:
        lines.append(f"### {task.id}: {task.description}")
        lines.append(f"- **Model Router:** `{task.model_type}`")
        lines.append(f"- **Output Key:** `{task.output_key}`")
        lines.append(f"- **Anchor:** `{task.anchor.value}`")
        if task.depends_on:
            lines.append(f"- **Dependencies:** `{', '.join(task.depends_on)}`")
        lines.append(f"- **Execution Group:** `{task.parallel_group}`")
        lines.append("")
        
    log_file.write_text("\n".join(lines), encoding="utf-8")


def write_success_artifact(
    user_prompt: str,
    plan: TaskPlan,
    context: ContextDict,
    files: dict[str, str],
    output_dir: str,
) -> str:
    """
    Write a JSON artifact for a successful pipeline run.

    The artifact includes:
    - original user prompt
    - plan-level metadata
    - every task with its template and fully rendered prompt
    - final generated files

    The filename uses local date/time plus a short unique id:
        adp_run_YYYYMMDD_HHMMSS_<id>.json
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid4().hex[:8]
    artifact_name = f"adp_run_{timestamp}_{unique_id}.json"
    artifact_path = out_dir / artifact_name

    tasks_payload = []
    for task in plan.tasks:
        tasks_payload.append(
            {
                "id": task.id,
                "description": task.description,
                "model_type": task.model_type,
                "parallel_group": task.parallel_group,
                "depends_on": task.depends_on,
                "output_key": task.output_key,
                "anchor": task.anchor.value,
                "status": task.status.value,
                "retries": task.retries,
                "error": task.error,
                "input_text": task.input_text,
                "system_prompt_template": task.system_prompt_template,
                "rendered_system_prompt": fill_template(task.system_prompt_template, context),
                "output": task.output,
                "mcp_tools": task.mcp_tools,
                "mcp_tool_args": task.mcp_tool_args,
            }
        )

    generated_files = {
        filename: {
            "content": content,
            "bytes": len(content.encode("utf-8")),
        }
        for filename, content in files.items()
    }

    payload = {
        "run_id": unique_id,
        "created_at": datetime.now().isoformat(),
        "user_prompt": user_prompt,
        "write_to_file": plan.write_to_file,
        "output_filenames": plan.output_filenames,
        "final_output_keys": plan.final_output_keys,
        "tasks": tasks_payload,
        "generated_files": generated_files,
    }

    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(artifact_path)
