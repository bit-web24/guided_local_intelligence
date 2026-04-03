"""Tests for final output verification."""
from __future__ import annotations

from pathlib import Path

import pytest

from adp.engine.final_verifier import (
    FINAL_PROMPT_VERIFIER_PROMPT,
    OutputVerificationError,
    verify_assembly_inputs,
    verify_execution_succeeded,
    verify_files_match_user_prompt,
    verify_final_outputs,
    verify_written_outputs,
)
from adp.models.task import AnchorType, MicroTask, TaskPlan, TaskStatus


def _make_plan(write_to_file: bool = True) -> TaskPlan:
    task = MicroTask(
        id="t1",
        description="Task t1",
        system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
        input_text="run",
        output_key="app_code",
        depends_on=[],
        anchor=AnchorType.OUTPUT,
        parallel_group=0,
    )
    return TaskPlan(
        tasks=[task],
        final_output_keys=["app_code"],
        output_filenames=["app.py"] if write_to_file else [],
        write_to_file=write_to_file,
    )


def test_verify_assembly_inputs_rejects_missing_fragments():
    plan = _make_plan()

    with pytest.raises(OutputVerificationError, match="Missing final fragments"):
        verify_assembly_inputs(plan, {})


def test_verify_execution_succeeded_rejects_failed_or_skipped_tasks():
    plan = TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Task t1",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="app_code",
                depends_on=[],
                anchor=AnchorType.OUTPUT,
                parallel_group=0,
                status=TaskStatus.FAILED,
                error="validation failed",
            ),
            MicroTask(
                id="t2",
                description="Task t2",
                system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
                input_text="run",
                output_key="readme",
                depends_on=["t1"],
                anchor=AnchorType.OUTPUT,
                parallel_group=1,
                status=TaskStatus.SKIPPED,
                error="Skipped because dependency ['t1'] failed",
            ),
        ],
        final_output_keys=["app_code", "readme"],
        output_filenames=["app.py", "README.md"],
        write_to_file=True,
    )

    with pytest.raises(OutputVerificationError, match="Blocked tasks"):
        verify_execution_succeeded(plan)


def test_verify_final_outputs_accepts_valid_python():
    plan = _make_plan()
    verify_final_outputs(plan, {"app.py": "def main():\n    return 1\n"})


def test_verify_final_outputs_rejects_missing_file():
    plan = _make_plan()

    with pytest.raises(OutputVerificationError, match="expected files"):
        verify_final_outputs(plan, {})


def test_verify_final_outputs_rejects_unexpected_file():
    plan = _make_plan()

    with pytest.raises(OutputVerificationError, match="unexpected files"):
        verify_final_outputs(plan, {"app.py": "def main():\n    return 1\n", "extra.py": "pass"})


def test_verify_final_outputs_rejects_python_syntax_error():
    plan = _make_plan()

    with pytest.raises(OutputVerificationError, match="Python syntax verification failed"):
        verify_final_outputs(plan, {"app.py": "def broken(:\n    pass\n"})


def test_verify_final_outputs_rejects_missing_marker():
    plan = _make_plan()

    with pytest.raises(OutputVerificationError, match="contains '\\[MISSING\\]'"):
        verify_final_outputs(plan, {"app.py": "# [MISSING]\n"})


def test_verify_final_outputs_rejects_file_delimiters_in_text_mode():
    plan = _make_plan(write_to_file=False)

    with pytest.raises(OutputVerificationError, match="file delimiters"):
        verify_final_outputs(plan, {"__stdout__": "--- FILE: app.py ---\nhello\n--- END FILE ---"})


def test_verify_written_outputs_accepts_matching_disk_content(tmp_path: Path):
    plan = _make_plan()
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")

    verify_written_outputs(plan, {"app.py": "def main():\n    return 1\n"}, str(output_dir))


def test_verify_written_outputs_rejects_mismatched_disk_content(tmp_path: Path):
    plan = _make_plan()
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "app.py").write_text("def main():\n    return 2\n", encoding="utf-8")

    with pytest.raises(OutputVerificationError, match="does not match"):
        verify_written_outputs(plan, {"app.py": "def main():\n    return 1\n"}, str(output_dir))


@pytest.mark.asyncio
async def test_verify_files_match_user_prompt_accepts_pass():
    plan = _make_plan()

    with pytest.MonkeyPatch.context() as mp:
        async def _mock_call(**kwargs):
            assert "User request:" in kwargs["user_message"]
            assert "Files:" in kwargs["user_message"]
            return "PASS"

        mp.setattr("adp.engine.final_verifier.call_cloud_async", _mock_call)
        await verify_files_match_user_prompt(
            "Create a tiny app",
            plan,
            {"app.py": "def main():\n    return 1\n"},
        )


@pytest.mark.asyncio
async def test_verify_files_match_user_prompt_rejects_fail_verdict():
    plan = _make_plan()

    with pytest.MonkeyPatch.context() as mp:
        async def _mock_call(**kwargs):
            return "FAIL — file does not implement the requested behavior"

        mp.setattr("adp.engine.final_verifier.call_cloud_async", _mock_call)
        with pytest.raises(OutputVerificationError, match="do not satisfy the original prompt"):
            await verify_files_match_user_prompt(
                "Create a tiny app",
                plan,
                {"app.py": "def main():\n    return 1\n"},
            )
