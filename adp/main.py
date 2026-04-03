"""ADP CLI entry point.

Usage:
    adp [OPTIONS] [PROMPT]

Arguments:
    PROMPT    Task prompt (omit for interactive TUI mode)

Options:
    --output  -o  PATH   Output directory  [default: ./adp_output]
    --model   -m  TEXT   Override both local Ollama models
    --cloud-model TEXT   Override the cloud/planner model
    --coder-model TEXT   Override the local coder model
    --general-model TEXT Override the local general model
    --no-tui             Plain text output (for scripting/CI)
    --debug              Print all system prompts and raw outputs
    --version            Show version and exit
    --help               Show this message and exit
"""
from __future__ import annotations

import argparse
import sys
from functools import partial
from typing import Callable

from adp.agent_graph import run_agent_graph
from adp.config import DEFAULT_OUTPUT_DIR, get_model_config, set_model_config
from adp.engine.call_stats import reset_model_call_counts
from adp.engine.local_client import check_ollama_connection
from adp.models.task import PipelineResult
from adp.tui.app import TUICallbacks, interactive_loop, make_plain_callbacks, run_with_live
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
    resume_run_id: str | None = None,
) -> PipelineResult:
    """
    Run the LangGraph supervisor loop for the local-first agent.

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
    mcp_config = load_mcp_config()

    async with MCPClientManager() as mcp_manager:
        tool_registry = await mcp_manager.start(mcp_config)
        return await run_agent_graph(
            user_prompt=user_prompt,
            output_dir=output_dir,
            callbacks=callbacks,
            debug=debug,
            mcp_manager=mcp_manager,
            tool_registry=tool_registry,
            resume_run_id=resume_run_id,
        )


def run_pipeline(
    user_prompt: str,
    output_dir: str,
    callbacks: TUICallbacks,
    debug: bool = False,
    resume_run_id: str | None = None,
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
    reset_model_call_counts()
    return anyio.run(
        partial(run_pipeline_async, user_prompt, output_dir, callbacks, debug, resume_run_id),
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
        help="Override both local Ollama models (overrides env vars)",
    )
    parser.add_argument(
        "--cloud-model",
        default=None,
        metavar="MODEL",
        help="Override the cloud/planner model",
    )
    parser.add_argument(
        "--coder-model",
        default=None,
        metavar="MODEL",
        help="Override the local coder model",
    )
    parser.add_argument(
        "--general-model",
        default=None,
        metavar="MODEL",
        help="Override the local general model",
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
        "--resume",
        metavar="RUN_ID",
        help="Resume a prior run from output_dir/.gli_runs/<RUN_ID>/state.json",
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

    set_model_config(
        cloud=args.cloud_model,
        local=args.model,
        local_coder=args.coder_model,
        local_general=args.general_model,
    )
    models = get_model_config()

    output_dir: str = args.output
    no_tui: bool = args.no_tui
    debug: bool = args.debug
    resume_run_id: str | None = args.resume

    def check_ollama() -> bool:
        import anyio
        return anyio.run(check_ollama_connection, backend="asyncio")

    def pipeline_fn_factory(user_prompt: str, out_dir: str, resume_id: str | None = None) -> Callable:
        """Returns a callable(callbacks) that runs the full pipeline."""
        def _run(callbacks: TUICallbacks) -> PipelineResult:
            return run_pipeline(
                user_prompt,
                out_dir,
                callbacks,
                debug=debug,
                resume_run_id=resume_id,
            )
        return _run

    if args.prompt or resume_run_id:
        # Single-shot mode: prompt given on command line
        ollama_ok = check_ollama()
        if not ollama_ok:
            print(
                f"Warning: One or both local models not found "
                f"({models.local_coder}, {models.local_general}). "
                "Proceeding — calls may fail.",
                file=sys.stderr,
            )
        pipeline_fn = pipeline_fn_factory(args.prompt or "", output_dir, resume_run_id)
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
