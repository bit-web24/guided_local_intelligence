"""Rich panel renderers for the ADP TUI.

Each function returns a Rich renderable. No pipeline logic here — pure display.
The TUI controller (app.py) calls these on each refresh cycle.
"""
from __future__ import annotations

from rich.columns import Columns
from rich.console import Group as RichGroup
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from adp.config import CLOUD_MODEL, LOCAL_MODEL
from adp.models.task import MicroTask, TaskStatus
from adp.tui import themes as th


def _status_icon(status: TaskStatus) -> tuple[str, str]:
    """Returns (icon, color) for a task status."""
    return {
        TaskStatus.PENDING: (th.ICON_PENDING, th.COLOR_PENDING),
        TaskStatus.RUNNING: (th.ICON_RUNNING, th.COLOR_RUNNING),
        TaskStatus.DONE:    (th.ICON_DONE,    th.COLOR_DONE),
        TaskStatus.FAILED:  (th.ICON_FAILED,  th.COLOR_FAILED),
        TaskStatus.SKIPPED: (th.ICON_SKIPPED, th.COLOR_SKIPPED),
    }[status]


def render_header(stage: str, ollama_ok: bool) -> Panel:
    """Top header bar showing model names, stage, and Ollama connection status."""
    conn_icon = "●" if ollama_ok else "○"
    conn_color = "bold green" if ollama_ok else "bold red"
    conn_label = "Ollama connected" if ollama_ok else "Ollama disconnected"

    t = Text()
    t.append(f"{th.APP_TITLE}  ", style=th.COLOR_HEADER)
    t.append(f"{th.APP_SUBTITLE}", style=th.COLOR_TITLE)
    t.append("    ")
    t.append(f"cloud: ", style=th.COLOR_FOOTER)
    t.append(CLOUD_MODEL, style=th.COLOR_CLOUD)
    t.append("   ")
    t.append(f"local: ", style=th.COLOR_FOOTER)
    t.append(LOCAL_MODEL, style=th.COLOR_LOCAL)
    t.append("   ")
    t.append(f"{conn_icon} {conn_label}", style=conn_color)

    stage_label = th.STAGE_LABELS.get(stage, stage)
    t.append(f"   [{stage_label}]", style=th.COLOR_STAGE)

    return Panel(t, box=__import__("rich.box", fromlist=["ROUNDED"]).ROUNDED,
                 border_style=th.COLOR_BORDER, padding=(0, 1))


def render_task_list(tasks: list[MicroTask]) -> Panel:
    """Left panel — live task list with status icons."""
    table = Table.grid(padding=(0, 1))
    table.add_column(width=2)   # icon
    table.add_column(width=4)   # id
    table.add_column()           # description

    # Group indicator
    current_group: int | None = None
    for task in tasks:
        if task.parallel_group != current_group:
            current_group = task.parallel_group
            # Count running tasks in this group
            running = [t for t in tasks
                       if t.parallel_group == current_group
                       and t.status == TaskStatus.RUNNING]
            if len(running) > 1:
                table.add_row(
                    "",
                    Text(th.ICON_PARALLEL, style=th.COLOR_RUNNING),
                    Text(f"group {current_group} — {len(running)} parallel",
                         style=th.COLOR_FOOTER),
                )

        icon, color = _status_icon(task.status)
        table.add_row(
            Text(icon, style=color),
            Text(task.id, style=color),
            Text(task.description, style=color),
        )

    title = f"TASK PLAN ({len(tasks)} tasks)"
    return Panel(table, title=title, title_align="left",
                 border_style=th.COLOR_BORDER, padding=(0, 1))


def render_current_task(task: MicroTask | None, streamed_output: str) -> Panel:
    """Right panel — shows system prompt + live output for the active task."""
    if task is None:
        return Panel(
            Text("Waiting…", style=th.COLOR_FOOTER),
            title="CURRENT TASK",
            title_align="left",
            border_style=th.COLOR_BORDER,
        )

    icon, color = _status_icon(task.status)

    # System prompt display (syntax highlighted)
    prompt_display = Syntax(
        task.system_prompt_template[:800],   # cap for display
        "text",
        theme="monokai",
        word_wrap=True,
        background_color="default",
    )
    prompt_panel = Panel(
        prompt_display,
        title=f"[{color}]{icon} {task.id}[/] {task.description}",
        title_align="left",
        border_style=th.COLOR_BORDER,
        padding=(0, 1),
    )

    # Live output panel
    output_text = Text()
    if streamed_output:
        output_text.append(streamed_output, style=th.COLOR_STREAM)
        output_text.append(" ▌", style="blink bold white")
    elif task.status == TaskStatus.DONE and task.output:
        output_text.append(task.output[:600], style=th.COLOR_DONE)
    elif task.status == TaskStatus.FAILED:
        output_text.append(task.error or "Unknown error", style=th.COLOR_FAILED)
    else:
        output_text.append("Running…", style=th.COLOR_FOOTER)

    output_panel = Panel(
        output_text,
        title="Output",
        title_align="left",
        border_style=th.COLOR_BORDER,
        padding=(0, 1),
    )

    return Panel(
        RichGroup(prompt_panel, output_panel),
        title="CURRENT TASK",
        title_align="left",
        border_style=th.COLOR_BORDER,
    )


def render_output_files(filenames: list[str]) -> Panel:
    """Footer bar listing expected output filenames."""
    t = Text()
    t.append("OUTPUT FILES: ", style=th.COLOR_FOOTER)
    for i, name in enumerate(filenames):
        if i:
            t.append("  ")
        t.append(name, style=th.COLOR_FILE)
    return Panel(t, border_style=th.COLOR_BORDER, padding=(0, 1))


def render_footer() -> Text:
    """Key-binding hint bar."""
    t = Text(justify="left")
    hints = [
        ("[ctrl+c]", "cancel"),
        ("[ctrl+l]", "clear"),
        ("[↑↓]", "history"),
        ("[enter]", "submit"),
    ]
    for key, label in hints:
        t.append(key, style="bold white")
        t.append(f" {label}   ", style=th.COLOR_FOOTER)
    return t


def render_completion_summary(
    written: list[tuple[str, int]],
    output_dir: str,
) -> Panel:
    """Completion panel shown after all files are written."""
    table = Table.grid(padding=(0, 2))
    table.add_column()
    table.add_column()
    for filename, size in written:
        table.add_row(
            Text(f"  {th.ICON_DONE} {filename}", style=th.COLOR_DONE),
            Text(f"{size:,} bytes", style=th.COLOR_SIZE),
        )

    t = Text()
    t.append(f"\nAll files written to: ", style=th.COLOR_FOOTER)
    t.append(output_dir, style=th.COLOR_FILE)

    return Panel(
        RichGroup(table, t),
        title="[bold green]Pipeline Complete[/]",
        title_align="left",
        border_style="green",
        padding=(1, 2),
    )
