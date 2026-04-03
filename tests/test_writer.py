"""Tests for safe output file writing."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from adp.models.task import AnchorType, MicroTask, TaskPlan, TaskStatus
from adp.writer import write_output_files, write_success_artifact


def test_write_output_files_writes_relative_paths_under_output_dir(tmp_path: Path):
    output_dir = tmp_path / "out"

    written = write_output_files({"lib/main.py": "print('hi')\n"}, str(output_dir))

    assert written == [("lib/main.py", len("print('hi')\n".encode("utf-8")))]
    assert (output_dir / "lib" / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert not any(p.suffix == ".tmp" for p in (output_dir / "lib").iterdir())


def test_write_output_files_rejects_absolute_paths(tmp_path: Path):
    output_dir = tmp_path / "out"
    absolute_file = tmp_path / "main.py"

    with pytest.raises(ValueError, match="relative paths"):
        write_output_files({str(absolute_file): "print('hi')\n"}, str(output_dir))


def test_write_output_files_rejects_parent_directory_escape(tmp_path: Path):
    output_dir = tmp_path / "out"

    with pytest.raises(ValueError, match="relative paths"):
        write_output_files({"../main.py": "print('hi')\n"}, str(output_dir))


def test_write_success_artifact_contains_tasks_prompts_and_generated_files(tmp_path: Path):
    output_dir = tmp_path / "out"
    plan = TaskPlan(
        tasks=[
            MicroTask(
                id="t1",
                description="Write hello endpoint",
                system_prompt_template=(
                    "You are a tiny coder.\n\nEXAMPLES:\n"
                    "Input: hi\nCode: return 'hi'\n\n---\n"
                    "Context: {route_contract}\nInput: {input_text}\nCode:"
                ),
                input_text="Write the endpoint body.",
                output_key="hello_endpoint",
                depends_on=[],
                anchor=AnchorType.CODE,
                parallel_group=0,
                model_type="coder",
                status=TaskStatus.DONE,
                output="def hello():\n    return {'message': 'Hello'}",
            )
        ],
        final_output_keys=["hello_endpoint"],
        output_filenames=["app.py"],
        write_to_file=True,
    )
    context = {
        "route_contract": "GET / returns {'message': 'Hello'}",
        "hello_endpoint": "def hello():\n    return {'message': 'Hello'}",
    }
    files = {"app.py": "from flask import Flask\n"}

    artifact_path = write_success_artifact(
        user_prompt="Create a tiny Flask app.",
        plan=plan,
        context=context,
        files=files,
        output_dir=str(output_dir),
    )

    artifact_file = Path(artifact_path)
    assert artifact_file.exists()
    assert re.fullmatch(r"adp_run_\d{8}_\d{6}_[0-9a-f]{8}\.json", artifact_file.name)

    data = json.loads(artifact_file.read_text(encoding="utf-8"))
    assert data["user_prompt"] == "Create a tiny Flask app."
    assert data["write_to_file"] is True
    assert data["output_filenames"] == ["app.py"]
    assert data["generated_files"]["app.py"]["content"] == "from flask import Flask\n"
    assert data["generated_files"]["app.py"]["bytes"] == len(
        "from flask import Flask\n".encode("utf-8")
    )
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["system_prompt_template"].endswith("Code:")
    assert "GET / returns {'message': 'Hello'}" in data["tasks"][0]["rendered_system_prompt"]
    assert data["tasks"][0]["output"] == "def hello():\n    return {'message': 'Hello'}"
