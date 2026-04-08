"""Tests for deterministic prompt fast-path answers."""
from __future__ import annotations

from adp.engine.quick_answers import maybe_answer_simple_temporal_prompt


def test_returns_answer_for_today_day_prompt():
    result = maybe_answer_simple_temporal_prompt("what is today's day?")
    assert result is not None
    assert result.startswith("Today is ")
    assert "(" in result and ")" in result


def test_returns_none_for_non_temporal_prompt():
    assert maybe_answer_simple_temporal_prompt("create a fastapi service") is None


def test_returns_none_for_tool_or_file_workflow_prompt():
    assert (
        maybe_answer_simple_temporal_prompt(
            "search web for today's date and write it to a file"
        )
        is None
    )


def test_returns_none_for_explicit_web_search_prompt():
    assert maybe_answer_simple_temporal_prompt("search the web to fetch today's date and year") is None
