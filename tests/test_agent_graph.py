"""Tests for the LangGraph supervisor loop."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from adp.agent_graph import run_agent_graph
from adp.engine.run_store import generate_run_id, save_run_state
from adp.models.task import AnchorType, MicroTask, TaskPlan, TaskStatus


@dataclass
class _Callbacks:
    stages: list[str] = field(default_factory=list)
    plans: list[TaskPlan] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    completed: list[tuple[list[tuple[str, int]], str, str | None]] = field(default_factory=list)
    retries: list[tuple[int, str]] = field(default_factory=list)
    tools: list[tuple[str, str, bool | None]] = field(default_factory=list)

    def on_stage(self, stage: str) -> None:
        self.stages.append(stage)

    def on_plan_ready(self, plan: TaskPlan) -> None:
        self.plans.append(plan)

    def on_decomposition_retry(self, attempt: int, reason: str) -> None:
        self.retries.append((attempt, reason))

    def on_task_start(self, task: MicroTask) -> None:
        return None

    def on_task_done(self, task: MicroTask) -> None:
        return None

    def on_task_failed(self, task: MicroTask) -> None:
        return None

    def on_tool_start(self, task: MicroTask, tool_name: str) -> None:
        self.tools.append((task.id, tool_name, None))

    def on_tool_done(self, task: MicroTask, tool_name: str, ok: bool, detail: str | None) -> None:
        self.tools.append((task.id, tool_name, ok))

    def on_complete(self, written: list[tuple[str, int]], output_dir: str, stdout_text: str | None = None) -> None:
        self.completed.append((written, output_dir, stdout_text))

    def on_error(self, message: str) -> None:
        self.errors.append(message)


def _make_text_plan(output_key: str = "answer") -> TaskPlan:
    return TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Task t1",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key=output_key,
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
            )
        ],
        final_output_keys=[output_key],
        output_filenames=[],
        write_to_file=False,
    )


@pytest.mark.asyncio
async def test_graph_replans_after_failed_execution(tmp_path):
    callbacks = _Callbacks()
    first_plan = _make_text_plan()
    second_plan = _make_text_plan()

    async def execute_side_effect(plan, *args, **kwargs):
        if plan is first_plan:
            plan.tasks[0].status = TaskStatus.FAILED
            plan.tasks[0].error = "validation failed"
            return {}
        plan.tasks[0].status = TaskStatus.DONE
        plan.tasks[0].output = "final answer"
        return {"answer": "final answer"}

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=first_plan)), \
         patch("adp.agent_graph.replan", AsyncMock(return_value=second_plan)) as replan_mock, \
         patch("adp.agent_graph.execute_plan", AsyncMock(side_effect=execute_side_effect)), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch("adp.agent_graph.assemble", AsyncMock(return_value={"__stdout__": "done"})):
        result = await run_agent_graph(
            user_prompt="Say hello",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=None,
            tool_registry=None,
        )

    assert result.files["__stdout__"] == "done"
    assert "REPLANNING" in callbacks.stages
    assert replan_mock.await_count == 1


@pytest.mark.asyncio
async def test_graph_does_not_replan_on_reflection_failures(tmp_path):
    callbacks = _Callbacks()
    plan = _make_text_plan()
    plan.tasks[0].status = TaskStatus.DONE
    plan.tasks[0].output = "answer"

    class _R:
        task_id = "t1"
        passed = False
        reason = "minor reflection mismatch"
        used_cloud = True

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=plan)), \
         patch("adp.agent_graph.execute_plan", AsyncMock(return_value={"answer": "answer"})), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[_R()])), \
         patch("adp.agent_graph.assemble", AsyncMock(return_value={"__stdout__": "done"})), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch("adp.agent_graph.replan", AsyncMock()) as replan_mock:
        result = await run_agent_graph(
            user_prompt="Say hello",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=None,
            tool_registry=None,
        )

    assert result.files["__stdout__"] == "done"
    assert replan_mock.await_count == 0


@pytest.mark.asyncio
async def test_graph_resumes_from_persisted_run_state(tmp_path):
    callbacks = _Callbacks()
    run_id = generate_run_id()
    plan = TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Task t1",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="schema",
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
                status=TaskStatus.DONE,
                output="schema-value",
            ),
            MicroTask(
                id="t2",
                description="Task t2",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nContext: {schema}\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="answer",
                depends_on=["t1"],
                anchor=AnchorType.OUTPUT,
                parallel_group=1,
                status=TaskStatus.PENDING,
            ),
        ],
        final_output_keys=["answer"],
        output_filenames=[],
        write_to_file=False,
    )
    save_run_state(
        output_dir=str(tmp_path),
        run_id=run_id,
        user_prompt="Resume me",
        plan=plan,
        context={"schema": "schema-value"},
        files={},
        status="executed",
        completed_stages=["plan", "execute"],
        replan_count=0,
        max_replans=2,
    )

    async def execute_side_effect(plan, *args, **kwargs):
        assert kwargs["initial_context"]["schema"] == "schema-value"
        plan.tasks[1].status = TaskStatus.DONE
        plan.tasks[1].output = "resumed answer"
        return {"schema": "schema-value", "answer": "resumed answer"}

    with patch("adp.agent_graph.execute_plan", AsyncMock(side_effect=execute_side_effect)) as execute_mock, \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch("adp.agent_graph.assemble", AsyncMock(return_value={"__stdout__": "done"})):
        result = await run_agent_graph(
            user_prompt="",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=None,
            tool_registry=None,
            resume_run_id=run_id,
        )

    assert result.context["answer"] == "resumed answer"
    assert execute_mock.await_count == 1
    assert "RESUMING" in callbacks.stages


@pytest.mark.asyncio
async def test_graph_resumes_from_assembled_state_without_reexecution(tmp_path):
    callbacks = _Callbacks()
    run_id = generate_run_id()
    plan = _make_text_plan()
    plan.tasks[0].status = TaskStatus.DONE
    plan.tasks[0].output = "final answer"
    save_run_state(
        output_dir=str(tmp_path),
        run_id=run_id,
        user_prompt="Resume finalize only",
        plan=plan,
        context={"answer": "final answer"},
        files={"__stdout__": "done"},
        status="assembled",
        completed_stages=["plan", "execute", "assemble"],
        replan_count=0,
        max_replans=2,
    )

    with patch("adp.agent_graph.execute_plan", AsyncMock()) as execute_mock, \
         patch("adp.agent_graph.reflect_plan", AsyncMock()) as reflect_mock, \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch("adp.agent_graph.write_text_file_via_mcp", AsyncMock()):
        result = await run_agent_graph(
            user_prompt="",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=object(),
            tool_registry=None,
            resume_run_id=run_id,
        )

    assert result.files["__stdout__"] == "done"
    assert execute_mock.await_count == 0
    assert reflect_mock.await_count == 0
    assert "RESUMING" in callbacks.stages


@pytest.mark.asyncio
async def test_graph_reports_internal_filesystem_writes_as_tools(tmp_path):
    callbacks = _Callbacks()
    plan = TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Write markdown content",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="markdown_content",
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
                status=TaskStatus.DONE,
                output="# Title\n\nLong enough content.\n" * 30,
            )
        ],
        final_output_keys=["markdown_content"],
        output_filenames=["books_api/README.md"],
        write_to_file=True,
    )

    class _MCP:
        async def call_tool(self, tool_name, arguments):
            path = arguments["path"]
            from pathlib import Path
            if tool_name == "create_directory":
                Path(path).mkdir(parents=True, exist_ok=True)
            elif tool_name == "write_file":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(arguments["content"], encoding="utf-8")
            return "ok"

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=plan)), \
         patch("adp.agent_graph.execute_plan", AsyncMock(return_value={"markdown_content": plan.tasks[0].output})), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch("adp.agent_graph.write_text_file_via_mcp", AsyncMock(return_value="ok")):
        await run_agent_graph(
            user_prompt="Write README into books_api directory",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=_MCP(),
            tool_registry=None,
        )

    tool_names = [name for _task_id, name, _ok in callbacks.tools]
    assert "create_directory" in tool_names
    assert "write_file" in tool_names
    assert any(task_id == "finalize" for task_id, _name, _ok in callbacks.tools)


@pytest.mark.asyncio
async def test_graph_recovers_non_empty_text_output_from_context(tmp_path):
    callbacks = _Callbacks()
    plan = _make_text_plan(output_key="final_date")
    plan.tasks[0].status = TaskStatus.DONE
    plan.tasks[0].output = "2026-04-08"

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=plan)), \
         patch("adp.agent_graph.execute_plan", AsyncMock(return_value={"final_date": "2026-04-08"})), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch("adp.agent_graph.assemble", AsyncMock(return_value={"__stdout__": ""})):
        result = await run_agent_graph(
            user_prompt="Return today's date only",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=None,
            tool_registry=None,
        )

    assert result.files["__stdout__"] == "2026-04-08"
    assert callbacks.completed[-1][2] == "2026-04-08"


@pytest.mark.asyncio
async def test_graph_patches_unresolved_temporal_template_tokens(tmp_path):
    callbacks = _Callbacks()
    plan = _make_text_plan(output_key="answer")
    plan.tasks[0].status = TaskStatus.DONE
    plan.tasks[0].output = "ok"

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=plan)), \
         patch("adp.agent_graph.execute_plan", AsyncMock(return_value={"answer": "ok"})), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch(
             "adp.agent_graph.assemble",
             AsyncMock(
                 return_value={
                     "__stdout__": "Today is [insert current date] and this year is [current year]."
                 }
             ),
         ):
        result = await run_agent_graph(
            user_prompt="Search the web to fetch today's date and year and return plain text",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=None,
            tool_registry=None,
        )

    text = result.files["__stdout__"]
    assert "[insert current date]" not in text
    assert "[current year]" not in text
    assert "Today is " in text


@pytest.mark.asyncio
async def test_graph_fails_when_mcp_file_write_fails(tmp_path):
    callbacks = _Callbacks()
    plan = TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Write markdown content",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="markdown_content",
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
                status=TaskStatus.DONE,
                output="# Title\n\nhello\n",
            )
        ],
        final_output_keys=["markdown_content"],
        output_filenames=["README.md"],
        write_to_file=True,
    )

    class _FailingMCP:
        async def call_tool(self, tool_name, arguments):
            raise RuntimeError(f"{tool_name} denied for {arguments.get('path')}")

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=plan)), \
         patch("adp.agent_graph.execute_plan", AsyncMock(return_value={"markdown_content": plan.tasks[0].output})), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)):
        with pytest.raises(RuntimeError, match="Written output verification failed"):
            await run_agent_graph(
                user_prompt="Write README",
                output_dir=str(tmp_path),
                callbacks=callbacks,
                mcp_manager=_FailingMCP(),
                tool_registry=None,
            )


@pytest.mark.asyncio
async def test_graph_fails_when_mcp_manager_missing_for_file_outputs(tmp_path):
    callbacks = _Callbacks()
    plan = TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Write markdown content",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="markdown_content",
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
                status=TaskStatus.DONE,
                output="# Title\n\nhello\n",
            )
        ],
        final_output_keys=["markdown_content"],
        output_filenames=["README.md"],
        write_to_file=True,
    )

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=plan)), \
         patch("adp.agent_graph.execute_plan", AsyncMock(return_value={"markdown_content": plan.tasks[0].output})), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)):
        with pytest.raises(RuntimeError, match="Filesystem MCP server is required"):
            await run_agent_graph(
                user_prompt="Write README",
                output_dir=str(tmp_path),
                callbacks=callbacks,
                mcp_manager=None,
                tool_registry=None,
            )


@pytest.mark.asyncio
async def test_graph_skips_finalize_artifact_writes_for_text_mode(tmp_path):
    callbacks = _Callbacks()
    plan = _make_text_plan(output_key="answer")
    plan.write_to_file = False
    plan.output_filenames = []

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=plan)), \
         patch("adp.agent_graph.execute_plan", AsyncMock(return_value={"answer": "hello"})), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch("adp.agent_graph.assemble", AsyncMock(return_value={"__stdout__": "hello"})), \
         patch("adp.agent_graph.write_text_file_via_mcp", AsyncMock()) as write_meta_mock:
        result = await run_agent_graph(
            user_prompt="search the web and tell me today's date",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=object(),
            tool_registry=None,
        )

    assert result.files["__stdout__"] == "hello"
    assert write_meta_mock.await_count == 0


@pytest.mark.asyncio
async def test_graph_forces_current_date_for_today_text_prompt(tmp_path):
    callbacks = _Callbacks()
    plan = _make_text_plan(output_key="answer")
    plan.write_to_file = False
    plan.output_filenames = []
    plan.tasks[0].status = TaskStatus.DONE
    plan.tasks[0].output = "stale"

    with patch("adp.agent_graph.decompose", AsyncMock(return_value=plan)), \
         patch("adp.agent_graph.execute_plan", AsyncMock(return_value={"answer": "stale"})), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch("adp.agent_graph.assemble", AsyncMock(return_value={"__stdout__": "Today is 2023."})):
        result = await run_agent_graph(
            user_prompt="search the web to fetch today's date and year",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=None,
            tool_registry=None,
        )

    from datetime import datetime
    expected_iso = datetime.now().astimezone().strftime("%Y-%m-%d")
    assert expected_iso in result.files["__stdout__"]


@pytest.mark.asyncio
async def test_graph_replaces_untrusted_source_links_with_tool_urls(tmp_path):
    callbacks = _Callbacks()
    plan = _make_text_plan(output_key="answer")
    plan.write_to_file = False
    plan.output_filenames = []
    plan.tasks[0].status = TaskStatus.DONE
    plan.tasks[0].output = "summary"

    search_payload = (
        '{"results":[{"url":"https://news.example.com/a"},'
        '{"url":"https://news.example.com/b"}]}'
    )
    with patch("adp.agent_graph.decompose", AsyncMock(return_value=plan)), \
         patch(
             "adp.agent_graph.execute_plan",
             AsyncMock(return_value={"answer": "summary", "t3_search_result": search_payload}),
         ), \
         patch("adp.agent_graph.reflect_plan", AsyncMock(return_value=[])), \
         patch("adp.agent_graph.verify_files_match_user_prompt", AsyncMock(return_value=None)), \
         patch(
             "adp.agent_graph.assemble",
             AsyncMock(
                 return_value={
                     "__stdout__": (
                         "Layoffs update. Sources: https://example.com/article1, "
                         "https://example.com/article2"
                     )
                 }
             ),
         ):
        result = await run_agent_graph(
            user_prompt="search the web to find current layoffs news and mention sources",
            output_dir=str(tmp_path),
            callbacks=callbacks,
            mcp_manager=None,
            tool_registry=None,
        )

    text = result.files["__stdout__"]
    assert "https://example.com/article1" not in text
    assert "https://news.example.com/a" in text
    assert "https://news.example.com/b" in text
