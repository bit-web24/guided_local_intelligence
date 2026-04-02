"""Tests for persisted run-state storage."""
from __future__ import annotations

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
        replan_count=1,
        max_replans=2,
    )

    loaded = load_run_state(str(tmp_path), run_id)
    assert loaded["run_id"] == run_id
    assert loaded["user_prompt"] == "Say hello"
    assert loaded["status"] == "succeeded"
    assert loaded["replan_count"] == 1
    assert loaded["files"]["__stdout__"] == "hello"
    assert loaded["plan"].tasks[0].status == TaskStatus.DONE
    assert loaded["plan"].tasks[0].output == "hello"
