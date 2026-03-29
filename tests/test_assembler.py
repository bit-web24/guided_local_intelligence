"""Tests for adp/stages/assembler.py."""
from adp.stages.assembler import _normalize_expected_files, _parse_file_delimiters


def test_normalize_expected_files_remaps_single_wrong_filename():
    files = {"main.py": "print('hello')"}
    normalized = _normalize_expected_files(files, "", ["holi_tui.py"])
    assert normalized == {"holi_tui.py": "print('hello')"}


def test_normalize_expected_files_uses_raw_fallback_for_single_expected_file():
    raw = "```python\nprint('hello')\n```"
    normalized = _normalize_expected_files({}, raw, ["holi_tui.py"])
    assert normalized == {"holi_tui.py": "print('hello')"}


def test_parse_file_delimiters_extracts_content():
    raw = "--- FILE: demo.py ---\nprint('ok')\n--- END FILE ---"
    files = _parse_file_delimiters(raw, ["demo.py"])
    assert files == {"demo.py": "print('ok')"}
