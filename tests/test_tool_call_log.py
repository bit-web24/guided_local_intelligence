"""Tests for session-scoped tool call logging."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import adp.engine.tool_call_log as tool_call_log
from adp.engine.tool_call_log import append_tool_call_log, reset_tool_call_log
from adp.main import run_pipeline
from adp.models.task import PipelineResult


def test_reset_tool_call_log_overwrites_existing_file(tmp_path: Path):
    log_path = tmp_path / "tool_calls.log"
    log_path.write_text("old content", encoding="utf-8")

    reset_tool_call_log(log_path)

    assert log_path.read_text(encoding="utf-8") == ""


def test_append_tool_call_log_writes_jsonl_records(tmp_path: Path):
    log_path = tmp_path / "tool_calls.log"
    reset_tool_call_log(log_path)

    append_tool_call_log(
        tool_name="read_file",
        arguments={"path": "/tmp/main.py"},
        output="print('hi')",
        log_path=log_path,
    )
    append_tool_call_log(
        tool_name="read_file",
        arguments={"path": "/tmp/missing.py"},
        error="File not found",
        log_path=log_path,
    )

    rows = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 2

    first = json.loads(rows[0])
    assert first["tool"] == "read_file"
    assert first["input"] == {"path": "/tmp/main.py"}
    assert first["ok"] is True
    assert first["output"] == "print('hi')"

    second = json.loads(rows[1])
    assert second["tool"] == "read_file"
    assert second["input"] == {"path": "/tmp/missing.py"}
    assert second["ok"] is False
    assert second["error"] == "File not found"


def test_run_pipeline_resets_tool_call_log_for_each_prompt(tmp_path: Path):
    log_path = tmp_path / "tool_calls.log"
    log_path.write_text("stale", encoding="utf-8")

    fake_result = PipelineResult(files={}, context={}, tasks=[])
    with patch("anyio.run", return_value=fake_result):
        with patch("adp.main.reset_model_call_counts"):
            with patch.object(tool_call_log, "_DEFAULT_LOG_PATH", log_path):
                run_pipeline(
                    user_prompt="hello",
                    output_dir=str(tmp_path / "out"),
                    callbacks=type(
                        "_Callbacks",
                        (),
                        {},
                    )(),
                )

    assert log_path.read_text(encoding="utf-8") == ""
