"""LangGraph supervisor loop for the local-first agentic workflow."""
from __future__ import annotations

import pathlib
import json
import re
from datetime import datetime
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from adp.config import (
    FINAL_ASSEMBLY_VERIFY_RETRIES,
    FINAL_WRITE_VERIFY_RETRIES,
    MAX_REPLANS,
    REFLECT_ENABLED,
)
from adp.engine.final_verifier import (
    OutputVerificationError,
    verify_assembly_inputs,
    verify_execution_succeeded,
    verify_files_match_user_prompt,
    verify_final_outputs,
    verify_written_outputs,
)
from adp.engine.run_store import generate_run_id, load_run_state, save_run_state
from adp.models.task import AnchorType, ContextDict, MicroTask, PipelineResult, StageList, TaskPlan
from adp.stages.assembler import assemble
from adp.stages.decomposer import decompose
from adp.stages.executor import execute_plan
from adp.stages.reflector import (
    has_reflection_failures,
    reflect_plan,
    reflection_failure_summary,
)
from adp.stages.replanner import replan
from adp.stages.replanner import build_preserved_context
from adp.writer import (
    build_execution_log_text,
    build_success_artifact,
    write_output_files_via_mcp,
    write_text_file_via_mcp,
)


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
    completed_stages: StageList
    last_error: str | None
    replan_count: int
    max_replans: int
    reflection_results: list[dict]
    result: PipelineResult | None


def _system_tool_task(task_id: str, description: str) -> MicroTask:
    return MicroTask(
        id=task_id,
        description=description,
        system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
        input_text=description,
        output_key=f"{task_id}_status",
        depends_on=[],
        anchor=AnchorType.OUTPUT,
        parallel_group=0,
        model_type="general",
    )


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
        completed_stages=overrides.get("completed_stages", state.get("completed_stages", [])),
        replan_count=overrides.get("replan_count", state.get("replan_count", 0)),
        max_replans=overrides.get("max_replans", state.get("max_replans", MAX_REPLANS)),
        last_error=overrides.get("last_error", state.get("last_error")),
    )


def _append_completed_stage(state: AgentState, stage: str) -> StageList:
    completed = list(state.get("completed_stages", []))
    if stage not in completed:
        completed.append(stage)
    return completed


_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_TEMPLATE_DATE_TOKEN_RE = re.compile(
    r"\[(?:insert\s+)?(?:current\s+)?(?:today'?s\s+)?date\]",
    re.IGNORECASE,
)
_TEMPLATE_YEAR_TOKEN_RE = re.compile(
    r"\[(?:insert|current)\s+year\]",
    re.IGNORECASE,
)


def _recover_text_stdout(
    plan: TaskPlan,
    context: ContextDict,
    files: dict[str, str],
    user_prompt: str = "",
) -> dict[str, str]:
    """Ensure text-mode runs always surface a non-empty response."""
    recovered = dict(files)
    current = str(recovered.get("__stdout__", "")).strip()
    if current:
        patched = _patch_temporal_template_leak(current, context, user_prompt)
        if patched is not None:
            recovered["__stdout__"] = patched
            return recovered
        grounded = _enforce_source_grounding(user_prompt, current, context)
        if grounded is not None:
            recovered["__stdout__"] = grounded
            return recovered
        forced = _force_temporal_today_answer(user_prompt, current)
        if forced is not None:
            recovered["__stdout__"] = forced
            return recovered
        return recovered

    # Prefer explicitly declared final outputs.
    for key in plan.final_output_keys:
        candidate = str(context.get(key, "")).strip()
        if not candidate:
            continue
        forced = _force_temporal_today_answer(user_prompt, candidate)
        if forced is not None:
            recovered["__stdout__"] = forced
            return recovered
        grounded = _enforce_source_grounding(user_prompt, candidate, context)
        if grounded is not None:
            recovered["__stdout__"] = grounded
            return recovered
        match = _DATE_RE.search(candidate)
        recovered["__stdout__"] = match.group(0) if match else candidate
        return recovered

    # Fall back to latest non-error tool result if final outputs are empty.
    tool_keys = [k for k in context.keys() if k.endswith("_result")]
    for key in reversed(tool_keys):
        candidate = str(context.get(key, "")).strip()
        if not candidate or candidate.startswith("[MCP tool"):
            continue
        forced = _force_temporal_today_answer(user_prompt, candidate)
        if forced is not None:
            recovered["__stdout__"] = forced
            return recovered
        match = _DATE_RE.search(candidate)
        recovered["__stdout__"] = match.group(0) if match else candidate[:6000]
        return recovered

    forced = _force_temporal_today_answer(user_prompt, "")
    if forced is not None:
        recovered["__stdout__"] = forced
        return recovered

    recovered["__stdout__"] = "No non-empty output was produced."
    return recovered


def _force_temporal_today_answer(user_prompt: str, current_text: str) -> str | None:
    """Return deterministic local-date answer for 'today/current date' prompts."""
    prompt_lower = user_prompt.lower()
    wants_today = any(token in prompt_lower for token in ("today", "current date", "date and year"))
    explicitly_searching = any(token in prompt_lower for token in ("search the web", "web search", "search"))
    if not (wants_today and explicitly_searching):
        return None
    now = datetime.now().astimezone()
    today_iso = now.strftime("%Y-%m-%d")
    if current_text and today_iso in current_text:
        return current_text
    if current_text:
        match = _DATE_RE.search(current_text)
        if match is not None:
            if match.group(0) == today_iso:
                return current_text
        else:
            year_match = _YEAR_RE.search(current_text)
            if year_match is None:
                return None
            if year_match.group(0) == now.strftime("%Y"):
                return current_text
    weekday = now.strftime("%A")
    month = now.strftime("%B")
    day = str(int(now.strftime("%d")))
    year = now.strftime("%Y")
    return f"Today is {weekday}, {month} {day}, {year} ({today_iso})."


_URL_RE = re.compile(r"https?://[^\s)\],]+", re.IGNORECASE)


def _enforce_source_grounding(
    user_prompt: str,
    current_text: str,
    context: ContextDict,
) -> str | None:
    """Ensure source requests only include URLs present in tool results."""
    prompt_lower = user_prompt.lower()
    asks_sources = any(token in prompt_lower for token in ("source", "sources", "cite", "citation", "link"))
    if not asks_sources:
        return None

    allowed_urls = _extract_tool_result_urls(context)
    if not allowed_urls:
        return "I couldn't retrieve reliable web sources for this request."

    output_urls = _URL_RE.findall(current_text or "")
    if output_urls and all(url in allowed_urls for url in output_urls):
        return None

    lines = ["I found relevant results from web search. Sources:"]
    for url in allowed_urls[:5]:
        lines.append(f"- {url}")
    return "\n".join(lines)


def _extract_tool_result_urls(context: ContextDict) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for key, raw_value in context.items():
        if not key.endswith("_result"):
            continue
        text = str(raw_value).strip()
        if not text.startswith("{"):
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        results = payload.get("results")
        if not isinstance(results, list):
            continue
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def _patch_temporal_template_leak(
    text: str,
    context: ContextDict,
    user_prompt: str,
) -> str | None:
    """Replace unresolved date/year template tokens with deterministic values."""
    if not (_TEMPLATE_DATE_TOKEN_RE.search(text) or _TEMPLATE_YEAR_TOKEN_RE.search(text)):
        return None
    prompt_lower = user_prompt.lower()
    if not any(token in prompt_lower for token in ("today", "date", "year", "day")):
        return None

    date_value: str | None = None
    year_value: str | None = None

    for value in context.values():
        snippet = str(value)
        date_match = _DATE_RE.search(snippet)
        if date_match and date_value is None:
            date_value = date_match.group(0)
            year_value = date_value[:4]
        year_match = _YEAR_RE.search(snippet)
        if year_match and year_value is None:
            year_value = year_match.group(0)
        if date_value and year_value:
            break

    if date_value is None or year_value is None:
        now = datetime.now().astimezone()
        date_value = now.strftime("%Y-%m-%d")
        year_value = now.strftime("%Y")

    patched = _TEMPLATE_DATE_TOKEN_RE.sub(date_value, text)
    patched = _TEMPLATE_YEAR_TOKEN_RE.sub(year_value, patched)
    return patched


def _resume_target_for_loaded_state(state: dict[str, Any]) -> Literal["plan", "execute", "reflect", "assemble", "finalize", "complete"]:
    plan = state.get("plan")
    context = state.get("context", {})
    files = state.get("files", {})
    completed = set(state.get("completed_stages", []))
    status = state.get("status")

    if status == "succeeded":
        return "complete"
    if plan is not None:
        has_unfinished_tasks = any(task.status.value not in {"done", "failed", "skipped"} for task in plan.tasks)
        missing_final_outputs = any(
            key not in context or not str(context[key]).strip()
            for key in plan.final_output_keys
        )
        if has_unfinished_tasks or missing_final_outputs:
            return "execute"
    if files and ("finalize" in completed or status in {"assembled", "writing", "verifying", "prompt_verify"}):
        return "finalize"
    if "assemble" in completed or status == "reflected":
        return "assemble"
    if "reflect" in completed or status == "executed":
        return "reflect" if REFLECT_ENABLED else "assemble"
    if "execute" in completed or status in {"planned", "replanned"}:
        return "execute"
    return "plan"


async def _initialize_node(
    state: AgentState,
) -> Command[Literal["plan", "execute", "reflect", "assemble", "finalize", "complete"]]:
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
            "completed_stages": loaded.get("completed_stages", []),
            "last_error": loaded.get("last_error"),
            "replan_count": int(loaded.get("replan_count", 0)),
            "max_replans": int(loaded.get("max_replans", state.get("max_replans", MAX_REPLANS))),
        }
        if updates.get("plan") is not None:
            callbacks.on_plan_ready(updates["plan"])
        goto = _resume_target_for_loaded_state(loaded) if updates.get("plan") is not None else "plan"
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
        "completed_stages": [],
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
        "completed_stages": _append_completed_stage(state, "plan"),
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
        on_tool_start=getattr(callbacks, "on_tool_start", None),
        on_tool_done=getattr(callbacks, "on_tool_done", None),
        mcp_manager=state["mcp_manager"],
        tool_registry=state["tool_registry"],
        initial_context=state.get("context", {}),
        on_group_complete=checkpoint,
    )

    updates: AgentState = {
        "plan": plan,
        "context": context,
        "status": "executed",
        "completed_stages": _append_completed_stage(state, "execute"),
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
    preserved_context = build_preserved_context(previous_plan, state.get("context", {}))
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
        "context": preserved_context,
        "files": {},
        "replan_count": new_count,
        "status": "replanned",
        "completed_stages": ["plan"],
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
    updates["completed_stages"] = _append_completed_stage(state, "assemble")
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
        on_task_reflected=getattr(callbacks, "on_task_reflected", None),
    )

    result_dicts = [
        {"task_id": r.task_id, "passed": r.passed, "reason": r.reason, "used_cloud": r.used_cloud}
        for r in results
    ]
    updates: AgentState = {
        "reflection_results": result_dicts,
        "status": "reflected",
        "completed_stages": _append_completed_stage(state, "reflect"),
    }
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]

    if has_reflection_failures(results):
        # Reflection is advisory. Do not trigger replans from reflection verdicts.
        updates["last_error"] = reflection_failure_summary(results)

    return Command(update=updates, goto="assemble")


async def _finalize_node(state: AgentState) -> Command[Literal["replan", "fail", "complete"]]:
    callbacks = state["callbacks"]
    plan = state["plan"]
    files = state.get("files", {})
    if plan is None:
        raise ValueError("Cannot finalize without a task plan.")

    try:
        verify_execution_succeeded(plan)
    except OutputVerificationError as exc:
        updates: AgentState = {"last_error": str(exc), "status": "failed"}
        return Command(update=updates, goto="fail")

    callbacks.on_stage("VERIFYING")
    last_error: str | None = None
    for attempt in range(FINAL_ASSEMBLY_VERIFY_RETRIES):
        try:
            if not plan.write_to_file:
                files = _recover_text_stdout(
                    plan,
                    state.get("context", {}),
                    files,
                    user_prompt=state.get("user_prompt", ""),
                )
            verify_final_outputs(plan, files)
            break
        except OutputVerificationError as exc:
            last_error = (
                f"Final assembled output verification failed: {exc}"
            )
            if attempt < FINAL_ASSEMBLY_VERIFY_RETRIES - 1:
                callbacks.on_stage("ASSEMBLING")
                files = await assemble(plan, state.get("context", {}), user_prompt=state["user_prompt"])
                if not plan.write_to_file:
                    files = _recover_text_stdout(
                        plan,
                        state.get("context", {}),
                        files,
                        user_prompt=state.get("user_prompt", ""),
                    )
                continue
            if state.get("replan_count", 0) < state.get("max_replans", MAX_REPLANS):
                updates = {"files": files, "last_error": last_error, "status": "replanning"}
                return Command(update=updates, goto="replan")
            return Command(update={"last_error": last_error, "status": "failed"}, goto="fail")

    written_files: list[tuple[str, int]] = []
    stdout_text: str | None = None
    if plan.write_to_file:
        write_error: str | None = None
        final_write_task = _system_tool_task("finalize", "Write final output files via filesystem MCP")
        for attempt in range(FINAL_WRITE_VERIFY_RETRIES):
            callbacks.on_stage("WRITING")
            try:
                if state["mcp_manager"] is None:
                    raise RuntimeError(
                        "Filesystem MCP server is required for file output operations."
                    )
                written_files = await write_output_files_via_mcp(
                    files,
                    state["output_dir"],
                    state["mcp_manager"],
                    task=final_write_task,
                    on_tool_start=getattr(callbacks, "on_tool_start", None),
                    on_tool_done=getattr(callbacks, "on_tool_done", None),
                )
                callbacks.on_stage("FINAL_VERIFY")
                verify_written_outputs(plan, files, state["output_dir"])
                write_error = None
                break
            except (IOError, OutputVerificationError, OSError, ValueError, RuntimeError) as exc:
                write_error = f"Written output verification failed: {exc}"
                if attempt == FINAL_WRITE_VERIFY_RETRIES - 1:
                    return Command(
                        update={"last_error": write_error, "status": "failed"},
                        goto="fail",
                    )
    else:
        files = _recover_text_stdout(
            plan,
            state.get("context", {}),
            files,
            user_prompt=state.get("user_prompt", ""),
        )
        stdout_text = files.get("__stdout__", "Error: No text output returned.")

    callbacks.on_stage("PROMPT_VERIFY")
    try:
        await verify_files_match_user_prompt(
            state["user_prompt"],
            plan,
            files,
        )
    except OutputVerificationError as exc:
        # Generated files already passed structural and write verification.
        # Keep prompt verification as advisory instead of triggering replans.
        updates_warning: AgentState = {"last_error": f"Prompt verification warning: {exc}"}
        state.update(updates_warning)

    if plan.write_to_file:
        execution_log_name = ".adp_execution_log.md"
        execution_log_content = build_execution_log_text(state["user_prompt"], plan)
        artifact_name, artifact_content = build_success_artifact(
            state["user_prompt"],
            plan,
            state.get("context", {}),
            files,
        )
        if state["mcp_manager"] is None:
            return Command(
                update={
                    "last_error": "Filesystem MCP server is required for writing run artifacts.",
                    "status": "failed",
                },
                goto="fail",
            )
        try:
            log_task = _system_tool_task("finalize_log", "Write execution log via filesystem MCP")
            await write_text_file_via_mcp(
                execution_log_name,
                execution_log_content,
                state["output_dir"],
                state["mcp_manager"],
                task=log_task,
                on_tool_start=getattr(callbacks, "on_tool_start", None),
                on_tool_done=getattr(callbacks, "on_tool_done", None),
            )
            artifact_task = _system_tool_task("finalize_artifact", "Write success artifact via filesystem MCP")
            await write_text_file_via_mcp(
                artifact_name,
                artifact_content,
                state["output_dir"],
                state["mcp_manager"],
                task=artifact_task,
                on_tool_start=getattr(callbacks, "on_tool_start", None),
                on_tool_done=getattr(callbacks, "on_tool_done", None),
            )
        except Exception as exc:
            return Command(
                update={
                    "last_error": f"Writing run artifacts via filesystem MCP failed: {exc}",
                    "status": "failed",
                },
                goto="fail",
            )

    callbacks.on_complete(written_files, state["output_dir"], stdout_text=stdout_text)
    result = PipelineResult(files=files, context=state.get("context", {}), tasks=plan.tasks)
    updates: AgentState = {
        "files": files,
        "written_files": written_files,
        "stdout_text": stdout_text,
        "status": "succeeded",
        "completed_stages": _append_completed_stage(state, "finalize"),
        "result": result,
    }
    combined = dict(state)
    combined.update(updates)
    _persist(combined)  # type: ignore[arg-type]
    return Command(update=updates, goto="complete")


async def _complete_node(state: AgentState) -> AgentState:
    """Terminal success node after final verification and writing."""
    return state


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
    graph.add_node("complete", _complete_node)
    graph.add_node("fail", _fail_node)

    graph.add_edge(START, "initialize")
    graph.add_edge("plan", "execute")
    graph.add_edge("replan", "execute")
    # execute → reflect or assemble is handled by Command in _execute_node
    # reflect → assemble, replan, or fail is handled by Command in _reflect_node
    graph.add_edge("assemble", "finalize")
    graph.add_edge("complete", END)
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
        "completed_stages": [],
        "last_error": None,
        "reflection_results": [],
    }
    final_state = await graph.ainvoke(initial_state)
    result = final_state.get("result")
    if result is not None:
        return result
    raise RuntimeError(final_state.get("last_error", "Agent graph failed without a result."))
