"""Claude-style Skill discovery, validation, and prompt formatting.

Skills are planning-time guidance only. They can shape the decomposed task
plan, but they cannot execute code or bypass ADP validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_XML_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "into", "it", "of", "on", "or", "the", "to", "use", "uses",
    "when", "with", "write", "writing",
}
_RESERVED_NAME_WORDS = {"anthropic", "claude"}


class SkillLoadError(ValueError):
    """Raised when a skill does not match the supported Skill.md contract."""


@dataclass(frozen=True)
class Skill:
    """A validated Claude-style skill loaded from a SKILL.md file."""

    name: str
    description: str
    body: str
    path: Path

    def prompt_block(self) -> str:
        body = self.body.strip()
        return (
            f"### Skill: {self.name}\n"
            f"Description: {self.description.strip()}\n"
            "Instructions:\n"
            f"{body}\n"
        )


def default_skill_roots(project_dir: str) -> list[Path]:
    """Return skill roots in deterministic preference order."""
    roots = [Path(project_dir).resolve() / ".claude" / "skills"]
    home = Path.home() / ".claude" / "skills"
    if home not in roots:
        roots.append(home)
    return roots


def load_skills_from_roots(roots: list[Path]) -> list[Skill]:
    """Load valid skills from root directories, skipping invalid entries."""
    skills: list[Skill] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for skill_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            try:
                skill = load_skill(skill_dir)
            except SkillLoadError:
                continue
            if skill.name in seen:
                continue
            seen.add(skill.name)
            skills.append(skill)
    return skills


def load_skill(skill_dir: Path) -> Skill:
    """Load and validate one skill directory containing SKILL.md."""
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.is_file():
        raise SkillLoadError(f"Skill directory '{skill_dir}' is missing SKILL.md.")

    raw = skill_path.read_text(encoding="utf-8")
    metadata, body = _parse_frontmatter(raw, skill_path)
    name = metadata.get("name", "").strip()
    description = metadata.get("description", "").strip()

    _validate_skill_metadata(name, description, skill_dir)
    if not body.strip():
        raise SkillLoadError(f"Skill '{name}' has empty instructions.")
    return Skill(name=name, description=description, body=body.strip(), path=skill_path)


def select_relevant_skills(
    user_prompt: str,
    skills: list[Skill],
    *,
    max_skills: int = 2,
) -> list[Skill]:
    """Select a small set of skills using deterministic lexical matching."""
    prompt_tokens = _tokens(user_prompt)
    if not prompt_tokens:
        return []

    scored: list[tuple[int, str, Skill]] = []
    lowered_prompt = user_prompt.lower()
    for skill in skills:
        skill_text = f"{skill.name.replace('-', ' ')} {skill.description}"
        skill_tokens = _tokens(skill_text)
        score = len(prompt_tokens & skill_tokens)
        if skill.name in lowered_prompt:
            score += 4
        if score <= 0:
            continue
        scored.append((score, skill.name, skill))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [skill for _score, _name, skill in scored[:max_skills]]


def format_skills_for_decomposer(skills: list[Skill]) -> str:
    """Build the decomposer prompt extension for selected skills."""
    if not skills:
        return ""
    blocks = "\n".join(skill.prompt_block() for skill in skills)
    return f"""\

SELECTED SKILLS:
The following Claude-style Skills matched this request. Use them only as
planning guidance. They do not override the core ADP schema, dependency,
placeholder, anchor, MCP, or final-output rules above.

{blocks}
SKILL RULES:
1. Apply selected Skills by producing better MicroTask descriptions,
   system_prompt_template examples, dependency shapes, tool hints, and
   validation-oriented task outputs.
2. Do not mention Skill names in final user-facing outputs unless the user asks.
3. If a Skill conflicts with the ADP schema or validation rules, ignore the
   conflicting Skill instruction and obey the ADP rule.
"""


def _parse_frontmatter(raw: str, skill_path: Path) -> tuple[dict[str, str], str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillLoadError(f"{skill_path} must start with YAML frontmatter.")

    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise SkillLoadError(f"{skill_path} frontmatter is not closed.")

    metadata: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise SkillLoadError(f"{skill_path} has invalid frontmatter line: {line}")
        key, value = stripped.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")

    return metadata, "\n".join(lines[end_index + 1 :])


def _validate_skill_metadata(name: str, description: str, skill_dir: Path) -> None:
    if not name:
        raise SkillLoadError("Skill frontmatter requires name.")
    if not _SKILL_NAME_RE.match(name):
        raise SkillLoadError(
            f"Skill name '{name}' must use lowercase letters, numbers, and hyphens only."
        )
    if any(word in _RESERVED_NAME_WORDS for word in name.split("-")):
        raise SkillLoadError(f"Skill name '{name}' contains a reserved word.")
    if skill_dir.name != name:
        raise SkillLoadError(
            f"Skill directory '{skill_dir.name}' must match frontmatter name '{name}'."
        )
    if not description:
        raise SkillLoadError(f"Skill '{name}' requires a non-empty description.")
    if len(description) > 1024:
        raise SkillLoadError(f"Skill '{name}' description exceeds 1024 characters.")
    if _XML_TAG_RE.search(name) or _XML_TAG_RE.search(description):
        raise SkillLoadError(f"Skill '{name}' metadata must not contain XML tags.")


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _WORD_RE.findall(text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    }
