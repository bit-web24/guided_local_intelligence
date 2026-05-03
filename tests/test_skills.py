"""Tests for Claude-style skill loading and selection."""
from __future__ import annotations

from pathlib import Path

import pytest

from adp.skills.loader import (
    SkillLoadError,
    default_skill_roots,
    format_skills_for_decomposer,
    load_skill,
    load_skills_from_roots,
    select_relevant_skills,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_skill(
    root: Path,
    name: str,
    description: str,
    body: str = "# Skill\n\n## Instructions\nDo the thing.",
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


def test_load_skill_uses_claude_style_frontmatter(tmp_path):
    skill_dir = _write_skill(
        tmp_path,
        "testing-code",
        "Plan robust tests. Use when writing pytest tests.",
    )

    skill = load_skill(skill_dir)

    assert skill.name == "testing-code"
    assert "pytest" in skill.description
    assert skill.path == skill_dir / "SKILL.md"


def test_load_skill_requires_directory_name_to_match_frontmatter(tmp_path):
    skill_dir = tmp_path / "wrong-name"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: testing-code\ndescription: Plan tests.\n---\n\n# Body\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillLoadError, match="must match"):
        load_skill(skill_dir)


def test_load_skill_rejects_reserved_claude_name(tmp_path):
    skill_dir = _write_skill(tmp_path, "claude-testing", "Reserved name example.")

    with pytest.raises(SkillLoadError, match="reserved"):
        load_skill(skill_dir)


def test_load_skills_skips_invalid_skill_without_failing_root(tmp_path):
    _write_skill(tmp_path, "testing-code", "Plan robust tests.")
    invalid = tmp_path / "bad"
    invalid.mkdir()
    (invalid / "SKILL.md").write_text("missing frontmatter", encoding="utf-8")

    skills = load_skills_from_roots([tmp_path])

    assert [skill.name for skill in skills] == ["testing-code"]


def test_select_relevant_skills_limits_and_sorts_by_score(tmp_path):
    testing = load_skill(_write_skill(tmp_path, "testing-code", "Use when writing pytest tests."))
    docs = load_skill(_write_skill(tmp_path, "writing-documentation", "Use when writing README docs."))
    api = load_skill(_write_skill(tmp_path, "documenting-apis", "Use when documenting API routes."))

    selected = select_relevant_skills(
        "Write pytest tests and documentation for the API.",
        [docs, testing, api],
        max_skills=2,
    )

    assert [skill.name for skill in selected] == ["testing-code", "documenting-apis"]


def test_project_skills_select_expected_samples():
    root = PROJECT_ROOT / ".claude" / "skills"
    skills = load_skills_from_roots([root])

    test_selected = select_relevant_skills(
        "Fix failing pytest and improve coverage.",
        skills,
    )
    docs_selected = select_relevant_skills(
        "Write README documentation and API usage examples.",
        skills,
    )

    assert test_selected[0].name == "testing-code"
    assert docs_selected[0].name == "writing-documentation"


def test_project_skills_select_websearch_to_file_workflow():
    root = PROJECT_ROOT / ".claude" / "skills"
    skills = load_skills_from_roots([root])

    selected = select_relevant_skills(
        "Search the web for LLM quantization sources and write the content into info/quantization.md.",
        skills,
    )

    assert selected[0].name == "websearch-to-file"


def test_project_websearch_skill_prefers_serpapi_search_tool():
    skill = load_skill(PROJECT_ROOT / ".claude" / "skills" / "websearch-to-file")

    assert "generic `search` MCP tool" in skill.body
    assert "google_light" in skill.body
    assert "duckduckgo" not in skill.body.lower()


def test_format_skills_for_decomposer_is_bounded_planning_guidance(tmp_path):
    skill = load_skill(_write_skill(tmp_path, "testing-code", "Use when writing pytest tests."))

    block = format_skills_for_decomposer([skill])

    assert "SELECTED SKILLS:" in block
    assert "### Skill: testing-code" in block
    assert "planning guidance" in block
    assert "do not override" in block.lower()


def test_default_skill_roots_prefers_project_skills(tmp_path):
    roots = default_skill_roots(str(tmp_path))

    assert roots[0] == tmp_path.resolve() / ".claude" / "skills"
