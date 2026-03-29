"""TUI controller — owns the Rich Live context and the render loop.

Terminal ownership lifecycle (Rich Live and prompt_toolkit cannot
both own the terminal simultaneously):

    1. prompt_toolkit collects user input → user presses Enter
    2. prompt_toolkit stops
    3. rich.live.Live starts (10 fps refresh)
    4. Pipeline runs in background thread (asyncio.run in ThreadPoolExecutor)
       → pipeline fires callbacks that update render_state (threading.Lock guarded)
       → Live loop reads render_state on each refresh
    5. Pipeline completes → Live stops
    6. Print completion summary (non-live rich.print)
    7. Go to step 1 (or exit on ctrl+c)

All TUI callbacks are non-blocking — they only update render_state dict.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

import rich.box as box
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live

from adp.models.task import MicroTask, TaskPlan, TaskStatus
from adp.tui import panels
from adp.tui.input_handler import get_user_prompt

console = Console()


# ---------------------------------------------------------------------------
# Shared render state — guarded by a threading.Lock
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()

_render_state: dict = {
    "tasks": [],
    "current_task": None,
    "streamed_output": "",
    "stage": "IDLE",
    "written_files": [],
    "output_dir": "",
    "ollama_ok": True,
    "output_filenames": [],
    "error": None,
}


def _update_state(**kwargs) -> None:
    """Thread-safe render state update. All callbacks call this."""
    with _state_lock:
        _render_state.update(kwargs)


def _read_state() -> dict:
    """Thread-safe render state snapshot for the Live render loop."""
    with _state_lock:
        return dict(_render_state)


# ---------------------------------------------------------------------------
# TUI Callbacks (fired from pipeline thread, non-blocking)
# ---------------------------------------------------------------------------
@dataclass
class TUICallbacks:
    on_stage: Callable[[str], None]
    on_plan_ready: Callable[[TaskPlan], None]
    on_task_start: Callable[[MicroTask], None]
    on_task_done: Callable[[MicroTask], None]
    on_task_failed: Callable[[MicroTask], None]
    on_complete: Callable[[list[tuple[str, int]], str, str | None], None]
    on_error: Callable[[str], None]


def make_tui_callbacks() -> TUICallbacks:
    """Create callbacks that update render_state (non-blocking)."""
    def on_stage(stage: str) -> None:
        _update_state(stage=stage)

    def on_plan_ready(plan: TaskPlan) -> None:
        _update_state(
            tasks=list(plan.tasks),
            output_filenames=list(plan.output_filenames),
        )

    def on_task_start(task: MicroTask) -> None:
        _update_state(current_task=task, streamed_output="")

    def on_task_done(task: MicroTask) -> None:
        with _state_lock:
            _render_state["tasks"] = list(_render_state["tasks"])
            current = _render_state.get("current_task")
            if current and current.id == task.id:
                _render_state["streamed_output"] = task.output or ""

    def on_task_failed(task: MicroTask) -> None:
        with _state_lock:
            _render_state["tasks"] = list(_render_state["tasks"])

    def on_complete(written: list[tuple[str, int]], output_dir: str, stdout_text: str | None = None) -> None:
        _update_state(
            stage="DONE",
            written_files=written,
            output_dir=output_dir,
            stdout_text=stdout_text,
        )

    def on_error(message: str) -> None:
        _update_state(stage="ERROR", error=message)

    return TUICallbacks(
        on_stage=on_stage,
        on_plan_ready=on_plan_ready,
        on_task_start=on_task_start,
        on_task_done=on_task_done,
        on_task_failed=on_task_failed,
        on_complete=on_complete,
        on_error=on_error,
    )


def make_plain_callbacks() -> TUICallbacks:
    """Create callbacks that just print to stdout (--no-tui mode)."""
    def on_stage(stage: str) -> None:
        console.print(f"[bold magenta][{stage}][/]")

    def on_plan_ready(plan: TaskPlan) -> None:
        console.print(f"[cyan]Plan: {len(plan.tasks)} tasks → {plan.output_filenames}[/]")

    def on_task_start(task: MicroTask) -> None:
        console.print(f"  [yellow]▶ {task.id}[/] {task.description}")

    def on_task_done(task: MicroTask) -> None:
        console.print(f"  [green]✓ {task.id}[/] done")

    def on_task_failed(task: MicroTask) -> None:
        icon = "✗" if task.status == TaskStatus.FAILED else "–"
        console.print(f"  [red]{icon} {task.id}[/] {task.error or 'failed'}")

    def on_complete(written: list[tuple[str, int]], output_dir: str, stdout_text: str | None = None) -> None:
        console.print("\n[bold green]Done![/]")
        if stdout_text:
            from rich.markdown import Markdown
            console.print(Markdown(stdout_text))
        else:
            console.print(f"Files written to [cyan]{output_dir}[/]")
            for fname, size in written:
                console.print(f"  [green]✓[/] {fname} ({size:,} bytes)")

    def on_error(message: str) -> None:
        console.print(f"[bold red]Error:[/] {message}")

    return TUICallbacks(
        on_stage=on_stage,
        on_plan_ready=on_plan_ready,
        on_task_start=on_task_start,
        on_task_done=on_task_done,
        on_task_failed=on_task_failed,
        on_complete=on_complete,
        on_error=on_error,
    )


# ---------------------------------------------------------------------------
# Live render loop
# ---------------------------------------------------------------------------
def _build_layout(state: dict) -> Layout:
    """Build the full terminal layout from current render state."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="files", size=3),
        Layout(name="footer", size=1),
    )
    layout["body"].split_row(
        Layout(name="tasks", ratio=2),
        Layout(name="current", ratio=3),
    )

    layout["header"].update(
        panels.render_header(state["stage"], state["ollama_ok"])
    )
    layout["tasks"].update(
        panels.render_task_list(state["tasks"])
    )
    layout["current"].update(
        panels.render_current_task(
            state["current_task"],
            state["streamed_output"],
        )
    )
    if state["output_filenames"]:
        layout["files"].update(panels.render_output_files(state["output_filenames"]))
    else:
        layout["files"].visible = False

    layout["footer"].update(panels.render_footer())

    return layout


def run_with_live(
    pipeline_fn,  # callable that takes TUICallbacks, runs pipeline, may raise
    output_dir: str,
    ollama_ok: bool,
) -> None:
    """
    Run `pipeline_fn` in a background thread while showing the Live TUI.

    1. Reset render state
    2. Start Live
    3. Run pipeline in ThreadPoolExecutor
    4. On each refresh, rebuild layout from render_state
    5. Stop Live when pipeline thread finishes
    """
    _update_state(
        tasks=[],
        current_task=None,
        streamed_output="",
        stage="IDLE",
        written_files=[],
        output_dir=output_dir,
        ollama_ok=ollama_ok,
        output_filenames=[],
        error=None,
    )

    callbacks = make_tui_callbacks()
    result_holder: dict = {"exc": None}

    def _run():
        try:
            pipeline_fn(callbacks)
        except Exception as e:
            result_holder["exc"] = e
            callbacks.on_error(str(e))

    with Live(
        _build_layout(_read_state()),
        console=console,
        refresh_per_second=10,
        screen=False,
    ) as live:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            while not future.done():
                live.update(_build_layout(_read_state()))
                import time; time.sleep(0.1)
            live.update(_build_layout(_read_state()))

    # Re-raise if pipeline failed
    if result_holder["exc"]:
        raise result_holder["exc"]

    # Print completion summary outside Live context (non-live rich.print)
    state = _read_state()
    if state.get("stdout_text"):
        console.print(panels.render_text_response(state["stdout_text"]))
    elif state["written_files"]:
        console.print(panels.render_completion_summary(
            state["written_files"],
            state["output_dir"],
        ))


def interactive_loop(
    pipeline_fn_factory: Callable[[str, str], Callable],
    output_dir: str,
    no_tui: bool,
    check_ollama_fn: Callable[[], bool],
) -> None:
    """
    REPL loop: collect prompt → run pipeline → repeat.

    pipeline_fn_factory(user_prompt, output_dir) → callable(callbacks)
    check_ollama_fn() → bool (called once per iteration)
    """
    console.print(f"\n[bold cyan]⬡ ADP[/] — Agentic Decomposition Pipeline")
    console.print(f"[dim]Type your prompt and press Enter. Ctrl+C to exit.[/]\n")

    while True:
        user_prompt = get_user_prompt(output_dir_hint=output_dir)
        if user_prompt is None:
            console.print("\n[dim]Bye.[/]")
            break
        user_prompt = user_prompt.strip()
        if not user_prompt:
            continue

        ollama_ok = check_ollama_fn()
        if not ollama_ok:
            console.print(
                "[bold red]Warning:[/] Ollama model not found. "
                "Proceeding anyway — calls may fail."
            )

        pipeline_fn = pipeline_fn_factory(user_prompt, output_dir)

        try:
            if no_tui:
                callbacks = make_plain_callbacks()
                pipeline_fn(callbacks)
            else:
                run_with_live(pipeline_fn, output_dir, ollama_ok)
        except Exception as e:
            console.print(f"\n[bold red]Pipeline error:[/] {e}")

        console.print()  # blank line before next prompt
