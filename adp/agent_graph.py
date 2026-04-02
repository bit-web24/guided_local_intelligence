"""LangGraph supervisor loop for the local-first agentic workflow."""
from __future__ import annotations

import pathlib
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from adp.config import MAX_REPLANS, REFLECT_ENABLED
from adp.engine.final_verifier import (
    OutputVerificationError,
    verify_assembly_inputs,
    verify_execution_succeeded,
    verify_final_outputs,
)
from adp.engine.run_store import generate_run_id, load_run_state, save_run_state
from adp.models.task import ContextDict, PipelineResult, TaskPlan
from adp.stages.assembler import assemble
from adp.stages.decomposer import decompose
from adp.stages.executor import execute_plan
from adp.stages.reflector import (
    has_reflection_failures,
    reflect_plan,
    reflection_failure_summary,
)
from adp.stages.replanner import replan
from adp.writer import write_execution_log, write_output_files, write_success_artifact


class AgentState(TypedDict, total=False):
    run_id: str
    resume_run_id: str | None
    user_prompt: str
    output_dir: str
    callbacks: Any
    debug: bool
    mcp_manager: Any
    tool_registry: Any
    project_dir: str
    plan: TaskPlan | None
    context: ContextDict
    files: dict[str, str]
    written_files: list[tuple[str, int]]
    stdout_text: str | None
    status: str
    last_error: str | None
    replan_count: int
    max_replans: int
    reflection_results: list[dict]
    result: PipelineResult | None


def _persist(state: AgentState, **overrides: Any) -> None:
    plan = overrides.get("plan", state.get("plan"))
    context = overrides.get("context", state.get("context", {}))
    files = overrides.get("files", state.get("files", {}))
    save_run_state(
        output_dir=state["output_dir"],
        run_id=overrides.get("run_id", state["run_id"]),
        user_prompt=overrides.get("user_prompt", state["user_prompt"]),
        plan=plan,
        context=context,
        files=files,
        status=overrides.get("status", state.get("status", "running")),
        replan_count=overrides.get("replan_count", state.get("replan_count", 0)),
        max_replans=overrides.get("max_replans", state.get("max_replans", MAX_REPLANS)),
        last_error=overrides.get("last_error", state.get("last_error")),
    )


async def _initialize_node(state: AgentState) -> Command[Literal["plan", "execute", "finalize"]]:
    callbacks = state["callbacks"]
    resume_run_id = state.get("resume_run_id")
    if resume_run_id:
        loaded = load_run_state(state["output_dir"], resume_run_id)
        if not loaded.get("user_prompt"):
            raise ValueError(f"Run '{resume_run_id}' is missing its original prompt.")
        callbacks.on_stage("RESUMING")
        updates: AgentState = {
            "run_id": loaded["run_id"],
            "user_prompt": loaded["user_prompt"],
            "plan": loaded.get("plan"),
            "context": loaded.get("context", {}),
            "files": loaded.get("files", {}),
            "status": loaded.get("status", "resumed"),
            "last_error": loaded.get("last_error"),
            "replan_count": int(loaded.get("replan_count", 0)),
            "max_replans": int(loaded.get("max_replans", state.get("max_replans", MAX_REPLANS))),
        }
        if updates.get("plan") is not None:
            callbacks.on_plan_ready(updates["plan"])
        goto = "plan"
        if updates.get("plan") is not None:
            goto = "finalize" if updates.get("files") else "execute"
        return Command(update=updates, goto=goto)

    run_id = generate_run_id()
    updates: AgentState = {
        "run_id": run_id,
        "plan": None,
        "context": {},
        "files": {},
        "written_files": [],
        "stdout_text": None,
        "status": "initialized",
        "last_error": None,
        "replan_count": 0,
        "max_replans": state.get("max_replans", MAX_REPLANS),
        "reflection_results": [],
    }
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]
    return Command(update=updates, goto="plan")


async def _plan_node(state: AgentState) -> AgentState:
    callbacks = state["callbacks"]
    callbacks.on_stage("DECOMPOSING")
    plan = await decompose(
        state["user_prompt"],
        tool_registry=state["tool_registry"],
        project_dir=state["project_dir"],
        on_retry=callbacks.on_decomposition_retry,
    )
    callbacks.on_plan_ready(plan)
    updates: AgentState = {
        "plan": plan,
        "context": {},
        "files": {},
        "status": "planned",
        "last_error": None,
    }
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]
    return updates


async def _execute_node(state: AgentState) -> Command[Literal["assemble", "replan", "fail"]]:
    callbacks = state["callbacks"]
    callbacks.on_stage("EXECUTING")
    plan = state["plan"]
    if plan is None:
        raise ValueError("Cannot execute without a task plan.")

    def checkpoint(plan_snapshot: TaskPlan, context_snapshot: ContextDict) -> None:
        combined = dict(state)
        combined.update({"plan": plan_snapshot, "context": context_snapshot, "status": "executing"})
        _persist(combined)  # type: ignore[arg-type]

    context = await execute_plan(
        plan,
        on_task_start=callbacks.on_task_start,
        on_task_done=callbacks.on_task_done,
        on_task_failed=callbacks.on_task_failed,
        mcp_manager=state["mcp_manager"],
        tool_registry=state["tool_registry"],
        initial_context=state.get("context", {}),
        on_group_complete=checkpoint,
    )

    updates: AgentState = {
        "plan": plan,
        "context": context,
        "status": "executed",
    }
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]
    try:
        verify_execution_succeeded(plan)
        if REFLECT_ENABLED:
            return Command(update=updates, goto="reflect")
        return Command(update=updates, goto="assemble")
    except OutputVerificationError as exc:
        if state.get("replan_count", 0) < state.get("max_replans", MAX_REPLANS):
            return Command(update=updates, goto="replan")
        updates["last_error"] = str(exc)
        return Command(update=updates, goto="fail")


async def _replan_node(state: AgentState) -> AgentState:
    callbacks = state["callbacks"]
    callbacks.on_stage("REPLANNING")
    previous_plan = state.get("plan")
    if previous_plan is None:
        raise ValueError("Cannot replan without an existing plan.")
    new_count = state.get("replan_count", 0) + 1
    plan = await replan(
        state["user_prompt"],
        previous_plan,
        tool_registry=state["tool_registry"],
        project_dir=state["project_dir"],
        on_retry=callbacks.on_decomposition_retry,
    )
    callbacks.on_plan_ready(plan)
    updates: AgentState = {
        "plan": plan,
        "context": {},
        "files": {},
        "replan_count": new_count,
        "status": "replanned",
        "last_error": None,
    }
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]
    return updates


async def _assemble_node(state: AgentState) -> AgentState:
    callbacks = state["callbacks"]
    callbacks.on_stage("ASSEMBLING")
    plan = state["plan"]
    context = state.get("context", {})
    if plan is None:
        raise ValueError("Cannot assemble without a task plan.")
    verify_assembly_inputs(plan, context)
    files = await assemble(plan, context, user_prompt=state["user_prompt"])
    updates: AgentState = {"files": files, "status": "assembled"}
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]
    return updates


async def _reflect_node(state: AgentState) -> Command[Literal["assemble", "replan", "fail"]]:
    """Per-task semantic reflection — validate each DONE task's output.

    Routes:
        - All reflections pass → assemble
        - Some reflections fail + replans left → replan
        - Some reflections fail + no replans left → fail
    """
    callbacks = state["callbacks"]
    callbacks.on_stage("REFLECTING")
    plan = state["plan"]
    context = state.get("context", {})
    if plan is None:
        raise ValueError("Cannot reflect without a task plan.")

    results = await reflect_plan(
        plan,
        context,
        on_task_reflected=callbacks.on_task_reflected,
    )

    result_dicts = [
        {"task_id": r.task_id, "passed": r.passed, "reason": r.reason, "used_cloud": r.used_cloud}
        for r in results
    ]
    updates: AgentState = {
        "reflection_results": result_dicts,
        "status": "reflected",
    }
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]

    if has_reflection_failures(results):
        summary = reflection_failure_summary(results)
        if state.get("replan_count", 0) < state.get("max_replans", MAX_REPLANS):
            updates["last_error"] = summary
            return Command(update=updates, goto="replan")
        updates["last_error"] = summary
        return Command(update=updates, goto="fail")

    return Command(update=updates, goto="assemble")


async def _finalize_node(state: AgentState) -> AgentState:
    callbacks = state["callbacks"]
    plan = state["plan"]
    files = state.get("files", {})
    if plan is None:
        raise ValueError("Cannot finalize without a task plan.")

    callbacks.on_stage("VERIFYING")
    verify_execution_succeeded(plan)
    verify_final_outputs(plan, files)

    callbacks.on_stage("WRITING")
    write_execution_log(state["user_prompt"], plan, state["output_dir"])
    write_success_artifact(
        state["user_prompt"],
        plan,
        state.get("context", {}),
        files,
        state["output_dir"],
    )

    written_files: list[tuple[str, int]] = []
    stdout_text: str | None = None
    if plan.write_to_file:
        written_files = write_output_files(files, state["output_dir"])
    else:
        stdout_text = files.get("__stdout__", "Error: No text output returned.")

    callbacks.on_complete(written_files, state["output_dir"], stdout_text=stdout_text)
    result = PipelineResult(files=files, context=state.get("context", {}), tasks=plan.tasks)
    updates: AgentState = {
        "written_files": written_files,
        "stdout_text": stdout_text,
        "status": "succeeded",
        "result": result,
    }
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]
    return updates


async def _fail_node(state: AgentState) -> AgentState:
    callbacks = state["callbacks"]
    plan = state.get("plan")
    last_error = state.get("last_error")
    if not last_error and plan is not None:
        try:
            verify_execution_succeeded(plan)
        except OutputVerificationError as exc:
            last_error = str(exc)
    if not last_error:
        last_error = "Pipeline failed without a recorded error."

    callbacks.on_error(last_error)
    updates: AgentState = {"status": "failed", "last_error": last_error}
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]
    return updates


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("initialize", _initialize_node)
    graph.add_node("plan", _plan_node)
    graph.add_node("execute", _execute_node)
    graph.add_node("replan", _replan_node)
    graph.add_node("reflect", _reflect_node)
    graph.add_node("assemble", _assemble_node)
    graph.add_node("finalize", _finalize_node)
    graph.add_node("fail", _fail_node)

    graph.add_edge(START, "initialize")
    graph.add_edge("plan", "execute")
    graph.add_edge("replan", "execute")
    # execute → reflect or assemble is handled by Command in _execute_node
    # reflect → assemble, replan, or fail is handled by Command in _reflect_node
    graph.add_edge("assemble", "finalize")
    graph.add_edge("finalize", END)
    graph.add_edge("fail", END)
    return graph.compile()


async def run_agent_graph(
    *,
    user_prompt: str,
    output_dir: str,
    callbacks: Any,
    debug: bool = False,
    mcp_manager: Any = None,
    tool_registry: Any = None,
    resume_run_id: str | None = None,
    max_replans: int = MAX_REPLANS,
) -> PipelineResult:
    """Execute the LangGraph supervisor loop and return the final pipeline result."""
    graph = build_agent_graph()
    initial_state: AgentState = {
        "resume_run_id": resume_run_id,
        "user_prompt": user_prompt,
        "output_dir": output_dir,
        "callbacks": callbacks,
        "debug": debug,
        "mcp_manager": mcp_manager,
        "tool_registry": tool_registry,
        "project_dir": str(pathlib.Path.cwd().resolve()),
        "max_replans": max_replans,
        "context": {},
        "files": {},
        "written_files": [],
        "stdout_text": None,
        "status": "created",
        "last_error": None,
        "reflection_results": [],
    }
    final_state = await graph.ainvoke(initial_state)
    result = final_state.get("result")
    if result is not None:
        return result
    raise RuntimeError(final_state.get("last_error", "Agent graph failed without a result."))
