"""Tests for safe output file writing."""
from __future__ import annotations

from pathlib import Path

import pytest

from adp.writer import write_output_files


def test_write_output_files_writes_relative_paths_under_output_dir(tmp_path: Path):
    output_dir = tmp_path / "out"

    written = write_output_files({"lib/main.py": "print('hi')\n"}, str(output_dir))

    assert written == [("lib/main.py", len("print('hi')\n".encode("utf-8")))]
    assert (output_dir / "lib" / "main.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_write_output_files_rejects_absolute_paths(tmp_path: Path):
    output_dir = tmp_path / "out"
    absolute_file = tmp_path / "main.py"

    with pytest.raises(ValueError, match="relative paths"):
        write_output_files({str(absolute_file): "print('hi')\n"}, str(output_dir))


def test_write_output_files_rejects_parent_directory_escape(tmp_path: Path):
    output_dir = tmp_path / "out"

    with pytest.raises(ValueError, match="relative paths"):
        write_output_files({"../main.py": "print('hi')\n"}, str(output_dir))
