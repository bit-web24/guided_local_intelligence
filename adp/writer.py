"""File writer — writes assembled output files to disk."""
from __future__ import annotations

from pathlib import Path

from adp.models.task import TaskPlan


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
        path = base / filename
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
