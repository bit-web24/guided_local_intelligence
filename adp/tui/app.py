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
from rich.style import Style
from rich.text import Text

from adp.models.task import MicroTask, ReflectionResult, TaskPlan, TaskStatus
from adp.config import DECOMPOSITION_MAX_RETRIES
from adp.engine.call_stats import get_model_call_counts, get_stage_model_call_counts
from adp.tui import panels
from adp.tui.input_handler import get_user_prompt

console = Console()

# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------
# GLI gradient colours — cyan → blue → magenta (left → right per row)
_BANNER_GRADIENT = [
    (0, 200, 255),
    (0, 150, 255),
    (80, 110, 255),
    (140, 80, 255),
    (190, 60, 220),
    (220, 80, 180),
]


def _lerp_color(t: float) -> tuple[int, int, int]:
    stops = _BANNER_GRADIENT
    scaled = t * (len(stops) - 1)
    lo = int(scaled)
    hi = min(lo + 1, len(stops) - 1)
    frac = scaled - lo

    r = int(stops[lo][0] + frac * (stops[hi][0] - stops[lo][0]))
    g = int(stops[lo][1] + frac * (stops[hi][1] - stops[lo][1]))
    b = int(stops[lo][2] + frac * (stops[hi][2] - stops[lo][2]))

    return r, g, b


def print_banner(version: str = "v1.0.0") -> None:
    try:
        import pyfiglet
        import shutil

        term_width = shutil.get_terminal_size().columns

        # Use structured multi-line instead of one long stretched line
        if term_width >= 110:
            font = "standard"
        elif term_width >= 80:
            font = "slant"
        else:
            font = "small"

        raw = pyfiglet.figlet_format(
            "Guided\nLocal\nIntelligence",
            font=font,
            width=term_width
        )

    except Exception:
        raw = "Guided Local Intelligence"

    lines = [l.rstrip() for l in raw.splitlines() if l.strip()]
    if not lines:
        return

    max_width = max(len(l) for l in lines)

    import shutil
    term_width = shutil.get_terminal_size().columns
    pad = max((term_width - max_width) // 2, 0)

    # Render gradient text
    for line in lines:
        t = Text(" " * pad)

        for i, ch in enumerate(line):
            col_t = i / max_width
            r, g, b = _lerp_color(col_t)

            t.append(
                ch,
                style=Style(color=f"rgb({r},{g},{b})", bold=True)
            )

        console.print(t)

    # Clean metadata section
    console.print(" " * pad + f"[dim]{version} • Local-first AI system[/dim]")
    console.print()

# ---------------------------------------------------------------------------
# Shared render state — guarded by a threading.Lock
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()

_render_state: dict = {
    "tasks": [],
    "current_task": None,
    "streamed_output": "",
    "activity": [],
    "tool_history": [],
    "stage": "IDLE",
    "written_files": [],
    "output_dir": "",
    "ollama_ok": True,
    "output_filenames": [],
    "error": None,
}

_MAX_ACTIVITY_ITEMS = 12
_MAX_TOOL_HISTORY_ITEMS = 20


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
    on_decomposition_retry: Callable[[int, str], None]
    on_task_start: Callable[[MicroTask], None]
    on_task_done: Callable[[MicroTask], None]
    on_task_failed: Callable[[MicroTask], None]
    on_tool_start: Callable[[MicroTask, str], None]
    on_tool_done: Callable[[MicroTask, str, bool, str | None], None]
    on_task_reflected: Callable[[MicroTask, ReflectionResult], None]
    on_complete: Callable[[list[tuple[str, int]], str, str | None], None]
    on_error: Callable[[str], None]


def make_tui_callbacks() -> TUICallbacks:
    """Create callbacks that update render_state (non-blocking)."""
    def append_activity(message: str) -> None:
        with _state_lock:
            activity = list(_render_state.get("activity", []))
            activity.append(message)
            _render_state["activity"] = activity[-_MAX_ACTIVITY_ITEMS:]

    def append_tool_history(message: str) -> None:
        with _state_lock:
            tool_history = list(_render_state.get("tool_history", []))
            tool_history.append(message)
            _render_state["tool_history"] = tool_history[-_MAX_TOOL_HISTORY_ITEMS:]

    def on_stage(stage: str) -> None:
        _update_state(stage=stage)
        append_activity(f"Stage: {stage}")

    def on_plan_ready(plan: TaskPlan) -> None:
        _update_state(
            tasks=list(plan.tasks),
            output_filenames=list(plan.output_filenames),
        )
        append_activity(f"Plan ready: {len(plan.tasks)} tasks")

    def on_decomposition_retry(attempt: int, reason: str) -> None:
        append_activity(f"Decomposition retry {attempt}/{DECOMPOSITION_MAX_RETRIES}: {reason}")

    def on_task_start(task: MicroTask) -> None:
        _update_state(current_task=task, streamed_output="")
        append_activity(f"{task.id} started: {task.description}")

    def on_task_done(task: MicroTask) -> None:
        with _state_lock:
            _render_state["tasks"] = list(_render_state["tasks"])
            current = _render_state.get("current_task")
            if current and current.id == task.id:
                _render_state["streamed_output"] = task.output or ""
        append_activity(f"{task.id} done")

    def on_task_failed(task: MicroTask) -> None:
        with _state_lock:
            _render_state["tasks"] = list(_render_state["tasks"])
        append_activity(f"{task.id} failed: {task.error or 'failed'}")

    def on_tool_start(task: MicroTask, tool_name: str) -> None:
        message = f"{task.id} call: {tool_name}"
        append_activity(f"[tool] {message}")
        append_tool_history(message)

    def on_tool_done(task: MicroTask, tool_name: str, ok: bool, detail: str | None) -> None:
        if ok:
            message = f"{task.id} done: {tool_name}"
            append_activity(f"[tool] {message}")
            append_tool_history(message)
        else:
            message = f"{task.id} failed: {tool_name} ({detail or 'failed'})"
            append_activity(f"[tool] {message}")
            append_tool_history(message)

    def on_task_reflected(task: MicroTask, result: ReflectionResult) -> None:
        verdict = "PASS" if result.passed else f"FAIL — {result.reason}"
        cloud_tag = " [cloud]" if result.used_cloud else ""
        append_activity(f"{task.id} reflected{cloud_tag}: {verdict}")

    def on_complete(written: list[tuple[str, int]], output_dir: str, stdout_text: str | None = None) -> None:
        _update_state(
            stage="DONE",
            written_files=written,
            output_dir=output_dir,
            stdout_text=stdout_text,
        )
        append_activity("Pipeline complete")

    def on_error(message: str) -> None:
        _update_state(stage="ERROR", error=message)
        append_activity(f"Pipeline error: {message}")

    return TUICallbacks(
        on_stage=on_stage,
        on_plan_ready=on_plan_ready,
        on_decomposition_retry=on_decomposition_retry,
        on_task_start=on_task_start,
        on_task_done=on_task_done,
        on_task_failed=on_task_failed,
        on_tool_start=on_tool_start,
        on_tool_done=on_tool_done,
        on_task_reflected=on_task_reflected,
        on_complete=on_complete,
        on_error=on_error,
    )


def make_plain_callbacks() -> TUICallbacks:
    """Create callbacks that just print to stdout (--no-tui mode)."""
    def on_stage(stage: str) -> None:
        console.print(f"[bold magenta][{stage}][/]")

    def on_plan_ready(plan: TaskPlan) -> None:
        console.print(f"[cyan]Plan: {len(plan.tasks)} tasks → {plan.output_filenames}[/]")

    def on_decomposition_retry(attempt: int, reason: str) -> None:
        console.print(
            f"  [yellow]↺ decompose {attempt}/{DECOMPOSITION_MAX_RETRIES}[/] {reason}"
        )

    def on_task_start(task: MicroTask) -> None:
        console.print(f"  [yellow]▶ {task.id}[/] {task.description}")

    def on_task_done(task: MicroTask) -> None:
        console.print(f"  [green]✓ {task.id}[/] done")

    def on_task_failed(task: MicroTask) -> None:
        icon = "✗" if task.status == TaskStatus.FAILED else "–"
        console.print(f"  [red]{icon} {task.id}[/] {task.error or 'failed'}")

    def on_tool_start(task: MicroTask, tool_name: str) -> None:
        console.print(f"  [cyan]↺ tool[/] {task.id} → {tool_name}")

    def on_tool_done(task: MicroTask, tool_name: str, ok: bool, detail: str | None) -> None:
        if ok:
            console.print(f"  [green]✓ tool[/] {task.id} → {tool_name}")
        else:
            console.print(f"  [red]✗ tool[/] {task.id} → {tool_name}: {detail or 'failed'}")

    def on_task_reflected(task: MicroTask, result: ReflectionResult) -> None:
        if result.passed:
            console.print(f"  [green]◉ {task.id}[/] reflected: PASS")
        else:
            console.print(f"  [red]◉ {task.id}[/] reflected: FAIL — {result.reason}")

    def on_complete(written: list[tuple[str, int]], output_dir: str, stdout_text: str | None = None) -> None:
        console.print("\n[bold green]Done![/]")
        if stdout_text:
            from rich.markdown import Markdown
            console.print(Markdown(stdout_text))
        else:
            console.print(f"Files written to [cyan]{output_dir}[/]")
            for fname, size in written:
                console.print(f"  [green]✓[/] {fname} ({size:,} bytes)")
        console.print(panels.render_model_call_summary(get_model_call_counts()))

    def on_error(message: str) -> None:
        console.print(f"[bold red]Error:[/] {message}")

    return TUICallbacks(
        on_stage=on_stage,
        on_plan_ready=on_plan_ready,
        on_decomposition_retry=on_decomposition_retry,
        on_task_start=on_task_start,
        on_task_done=on_task_done,
        on_task_failed=on_task_failed,
        on_tool_start=on_tool_start,
        on_tool_done=on_tool_done,
        on_task_reflected=on_task_reflected,
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
    layout["current"].split_column(
        Layout(name="current_task", ratio=2),
        Layout(name="lower", ratio=3),
    )
    layout["lower"].split_row(
        Layout(name="activity", ratio=3),
        Layout(name="tools", ratio=2),
    )

    layout["header"].update(
        panels.render_header(state["stage"], state["ollama_ok"])
    )
    layout["tasks"].update(
        panels.render_task_list(state["tasks"])
    )
    layout["current_task"].update(
        panels.render_current_task(
            state["current_task"],
            state["streamed_output"],
        )
    )
    layout["activity"].update(
        panels.render_activity(state["activity"], state.get("error"))
    )
    layout["tools"].update(
        panels.render_tool_history(state.get("tool_history", []))
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
        activity=[],
        tool_history=[],
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
            last_state = _read_state()
            while not future.done():
                state = _read_state()
                if state != last_state:
                    live.update(_build_layout(state))
                    last_state = state
                import time; time.sleep(0.1)
            state = _read_state()
            if state != last_state:
                live.update(_build_layout(state))

    # Re-raise if pipeline failed
    if result_holder["exc"]:
        raise result_holder["exc"]

    # Print completion summary outside Live context (non-live rich.print)
    state = _read_state()
    if state.get("stdout_text"):
        console.print(panels.render_text_response(state["stdout_text"]))
        console.print(
            panels.render_model_call_summary(
                get_model_call_counts(),
                get_stage_model_call_counts(),
            )
        )
    elif state["written_files"]:
        console.print(panels.render_completion_summary(
            state["written_files"],
            state["output_dir"],
            get_model_call_counts(),
            get_stage_model_call_counts(),
        ))


def interactive_loop(
    pipeline_fn_factory: Callable[[str, str], Callable],
    output_dir: str,
    no_tui: bool,
    check_ollama_fn: Callable[[], bool],
    clarify_prompt_fn: Callable[[str, str], str | None] | None = None,
) -> None:
    """
    REPL loop: collect prompt → run pipeline → repeat.

    pipeline_fn_factory(user_prompt, output_dir) → callable(callbacks)
    check_ollama_fn() → bool (called once per iteration)
    """
    print_banner()
    console.print(f"[dim]Type your prompt and press Enter. Ctrl+C to exit.[/]\n")

    while True:
        user_prompt = get_user_prompt()
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

        effective_prompt = user_prompt
        if clarify_prompt_fn is not None:
            clarified = clarify_prompt_fn(user_prompt, output_dir)
            if clarified is None:
                console.print("[dim]Cancelled during clarification.[/]")
                console.print()
                continue
            effective_prompt = clarified

        pipeline_fn = pipeline_fn_factory(effective_prompt, output_dir)

        try:
            if no_tui:
                callbacks = make_plain_callbacks()
                pipeline_fn(callbacks)
            else:
                run_with_live(pipeline_fn, output_dir, ollama_ok)
        except Exception as e:
            console.print(f"\n[bold red]Pipeline error:[/] {e}")

        console.print()  # blank line before next prompt
