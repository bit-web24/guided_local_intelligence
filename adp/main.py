"""ADP CLI entry point.

Usage:
    adp [OPTIONS] [PROMPT]

Arguments:
    PROMPT    Task prompt (omit for interactive TUI mode)

Options:
    --output  -o  PATH   Output directory  [default: ./adp_output]
    --model   -m  TEXT   Override local Ollama model
    --no-tui             Plain text output (for scripting/CI)
    --debug              Print all system prompts and raw outputs
    --version            Show version and exit
    --help               Show this message and exit
"""
from __future__ import annotations

import argparse
import os
import sys
from functools import partial
from typing import Callable

from adp.config import DEFAULT_OUTPUT_DIR, LOCAL_CODER_MODEL, LOCAL_GENERAL_MODEL, CLOUD_MODEL
from adp.engine.final_verifier import verify_assembly_inputs, verify_final_outputs
from adp.engine.local_client import check_ollama_connection
from adp.models.task import PipelineResult
from adp.stages.assembler import assemble
from adp.stages.decomposer import decompose
from adp.stages.executor import execute_plan
from adp.tui.app import TUICallbacks, interactive_loop, make_plain_callbacks, run_with_live
from adp.writer import write_output_files, write_execution_log, write_success_artifact
from adp.mcp.config import load_mcp_config
from adp.mcp.client import MCPClientManager

VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Core async pipeline
# ---------------------------------------------------------------------------
async def run_pipeline_async(
    user_prompt: str,
    output_dir: str,
    callbacks: TUICallbacks,
    debug: bool = False,
) -> PipelineResult:
    """
    Orchestrate all 4 stages: Decompose → Execute → Assemble → Write.

    MCP lifecycle:
    - load_mcp_config() reads mcp_servers.toml (empty = MCP disabled)
    - MCPClientManager starts all configured servers, builds ToolRegistry
    - ToolRegistry is passed to decompose() → Decomposer sees available tools
    - project_dir is passed so Decomposer writes correct absolute paths
    - mcp_manager is passed to execute_plan() → per-task pre-fetch runs
    - MCPClientManager.stop() is called on exit (via async context manager)

    The large model is called exactly twice:
    1. decompose()  → in stages/decomposer.py
    2. assemble()   → in stages/assembler.py
    """
    import pathlib
    # Resolve the project directory so the Decomposer can generate absolute
    # paths for MCP tool args (the filesystem server requires absolute paths).
    project_dir = str(pathlib.Path.cwd().resolve())
    mcp_config = load_mcp_config()

    async with MCPClientManager() as mcp_manager:
        # Start MCP servers and build tool registry (no-op if config empty)
        tool_registry = await mcp_manager.start(mcp_config)

        # Stage 1 — Decompose (large model)
        callbacks.on_stage("DECOMPOSING")
        plan = await decompose(user_prompt, tool_registry=tool_registry, project_dir=project_dir)
        callbacks.on_plan_ready(plan)

        if debug:
            print(f"\n[DEBUG] Task plan: {len(plan.tasks)} tasks")
            for t in plan.tasks:
                print(f"\n  [{t.id}] {t.description}")
                print(f"  group: {t.parallel_group}  depends: {t.depends_on}")
                if t.mcp_tools:
                    print(f"  mcp_tools: {t.mcp_tools}  args: {t.mcp_tool_args}")
                print(f"  --- system prompt ---")
                print(t.system_prompt_template)
                print(f"  ---")

        # Stage 2 — Execute (small model, parallel within groups)
        callbacks.on_stage("EXECUTING")
        context = await execute_plan(
            plan,
            on_task_start=callbacks.on_task_start,
            on_task_done=callbacks.on_task_done,
            on_task_failed=callbacks.on_task_failed,
            mcp_manager=mcp_manager,
            tool_registry=tool_registry,
        )

        if debug:
            print(f"\n[DEBUG] Context keys: {list(context.keys())}")

        # Stage 3 — Assemble (large model)
        callbacks.on_stage("ASSEMBLING")
        verify_assembly_inputs(plan, context)
        files = await assemble(plan, context, user_prompt=user_prompt)

        callbacks.on_stage("VERIFYING")
        verify_final_outputs(plan, files)

        # Stage 4 — Write or Print
        callbacks.on_stage("WRITING")

        # Always write an execution log regardless of text/file mode
        write_execution_log(user_prompt, plan, output_dir)

        if plan.write_to_file:
            written = write_output_files(files, output_dir)
            write_success_artifact(user_prompt, plan, context, files, output_dir)
            callbacks.on_complete(written, output_dir, stdout_text=None)
        else:
            text_output = files.get("__stdout__", "Error: No text output returned.")
            write_success_artifact(user_prompt, plan, context, files, output_dir)
            callbacks.on_complete([], output_dir, stdout_text=text_output)

    return PipelineResult(files=files, context=context, tasks=plan.tasks)


def run_pipeline(
    user_prompt: str,
    output_dir: str,
    callbacks: TUICallbacks,
    debug: bool = False,
) -> PipelineResult:
    """
    Synchronous wrapper around the async pipeline.

    Uses anyio.run() (not asyncio.run()) so that anyio's cancel scope and
    task-group machinery is fully initialised BEFORE any coroutines execute.
    asyncio.run() causes anyio to self-initialise lazily, which breaks
    BaseSession's create_task_group() cancel scope tracking under Python 3.14,
    triggering 'Attempted to exit cancel scope in a different task'.
    """
    import anyio
    return anyio.run(
        partial(run_pipeline_async, user_prompt, output_dir, callbacks, debug),
        backend="asyncio",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adp",
        description="Agentic Decomposition Pipeline — large model decomposes, small model executes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Task prompt. Omit for interactive TUI mode.",
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT_DIR,
        metavar="PATH",
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        metavar="MODEL",
        help="Override local Ollama models (overrides env vars)",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Plain text output — no live TUI (useful for CI/scripting)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print all system prompts and raw model outputs",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"adp {VERSION}",
    )
    return parser


def cli() -> None:
    """Main CLI entry point registered in pyproject.toml [project.scripts]."""
    parser = _build_parser()
    args = parser.parse_args()

    # Apply model override if given
    if args.model:
        os.environ["LOCAL_CODER_MODEL"] = args.model
        os.environ["LOCAL_GENERAL_MODEL"] = args.model

    output_dir: str = args.output
    no_tui: bool = args.no_tui
    debug: bool = args.debug

    def check_ollama() -> bool:
        import anyio
        return anyio.run(check_ollama_connection, backend="asyncio")

    def pipeline_fn_factory(user_prompt: str, out_dir: str) -> Callable:
        """Returns a callable(callbacks) that runs the full pipeline."""
        def _run(callbacks: TUICallbacks) -> PipelineResult:
            return run_pipeline(user_prompt, out_dir, callbacks, debug=debug)
        return _run

    if args.prompt:
        # Single-shot mode: prompt given on command line
        ollama_ok = check_ollama()
        if not ollama_ok:
            print(
                f"Warning: One or both local models not found. "
                "Proceeding — calls may fail.",
                file=sys.stderr,
            )
        pipeline_fn = pipeline_fn_factory(args.prompt, output_dir)
        try:
            if no_tui:
                callbacks = make_plain_callbacks()
                pipeline_fn(callbacks)
            else:
                run_with_live(pipeline_fn, output_dir, ollama_ok)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Interactive REPL mode
        interactive_loop(
            pipeline_fn_factory=pipeline_fn_factory,
            output_dir=output_dir,
            no_tui=no_tui,
            check_ollama_fn=check_ollama,
        )


if __name__ == "__main__":
    cli()
