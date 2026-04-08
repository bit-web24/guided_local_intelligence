"""Tests for persisted run-state storage."""
from __future__ import annotations

import json

from adp.engine import run_store
from adp.engine.run_store import generate_run_id, load_run_state, save_run_state
from adp.models.task import AnchorType, MicroTask, TaskPlan, TaskStatus


def test_save_and_load_run_state_round_trip(tmp_path):
    plan = TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Task t1",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="answer",
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
                status=TaskStatus.DONE,
                output="hello",
            )
        ],
        final_output_keys=["answer"],
        output_filenames=[],
        write_to_file=False,
    )
    run_id = generate_run_id()

    save_run_state(
        output_dir=str(tmp_path),
        run_id=run_id,
        user_prompt="Say hello",
        plan=plan,
        context={"answer": "hello"},
        files={"__stdout__": "hello"},
        status="succeeded",
        completed_stages=["plan", "execute", "assemble", "finalize"],
        replan_count=1,
        max_replans=2,
    )

    loaded = load_run_state(str(tmp_path), run_id)
    assert loaded["run_id"] == run_id
    assert loaded["user_prompt"] == "Say hello"
    assert loaded["status"] == "succeeded"
    assert loaded["completed_stages"] == ["plan", "execute", "assemble", "finalize"]
    assert loaded["replan_count"] == 1
    assert loaded["files"]["__stdout__"] == "hello"
    assert loaded["plan"].tasks[0].status == TaskStatus.DONE
    assert loaded["plan"].tasks[0].output == "hello"


def test_save_spills_large_context_and_loads_full_context(tmp_path, monkeypatch):
    monkeypatch.setattr(run_store, "RUN_STATE_INLINE_CONTEXT_MAX_CHARS", 32)

    run_id = generate_run_id()
    large_value = "x" * 200
    save_run_state(
        output_dir=str(tmp_path),
        run_id=run_id,
        user_prompt="Large context run",
        plan=None,
        context={"huge": large_value},
        files={},
        status="running",
        completed_stages=["plan"],
        replan_count=0,
        max_replans=2,
    )

    state_path = tmp_path / ".gli_runs" / run_id / "state.json"
    state_data = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_data["context_spilled"] is True
    assert state_data["context"]["huge"] == large_value

    loaded = load_run_state(str(tmp_path), run_id)
    assert loaded["context"]["huge"] == large_value
