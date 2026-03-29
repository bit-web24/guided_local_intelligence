"""Output extraction and validation by anchor type."""
from __future__ import annotations

import ast
import json
import re

from adp.models.task import AnchorType, MicroTask, ValidationResult


def extract_after_anchor(raw_output: str, anchor: AnchorType) -> str:
    """
    Strip any preamble before the anchor word.
    The model may echo the anchor word — extract only what comes AFTER
    the last occurrence of the anchor.
    """
    anchor_str = anchor.value
    idx = raw_output.rfind(anchor_str)
    if idx == -1:
        return raw_output.strip()
    return raw_output[idx + len(anchor_str):].strip()


def validate(output: str, anchor: AnchorType) -> tuple[bool, str]:
    """
    Returns (is_valid, cleaned_output).
    cleaned_output strips markdown fences and trailing garbage.

    Validation rules by anchor type:
    - JSON:     must parse as valid JSON object or array
    - CODE:     must be non-empty after stripping fences (> 10 chars)
    - TOML:     must parse with tomllib
    - OUTPUT:   non-empty check only
    - MARKDOWN: non-empty check only
    """
    if not output or not output.strip():
        return False, ""

    if anchor == AnchorType.JSON:
        clean = re.sub(r"```json\s*|\s*```", "", output).strip()
        # Trim anything after the closing brace/bracket
        match = re.search(r"(\{.*\}|\[.*\])", clean, re.DOTALL)
        if not match:
            return False, output
        try:
            json.loads(match.group(0))
            return True, match.group(0)
        except json.JSONDecodeError:
            return False, output

    if anchor == AnchorType.CODE:
        clean = re.sub(r"```\w*\n?|\n?```", "", output).strip()
        if len(clean) < 10:
            return False, output
        return True, clean

    if anchor == AnchorType.TOML:
        try:
            import tomllib  # stdlib in Python 3.11+
            tomllib.loads(output.strip())
            return True, output.strip()
        except Exception:
            return False, output

    # OUTPUT and MARKDOWN — non-empty check only
    return True, output.strip()


def validate_task_output(task: MicroTask, output: str) -> ValidationResult:
    """Validate output with generic anchor checks plus optional task-specific rules."""
    is_valid, cleaned = validate(output, task.anchor)
    if not is_valid:
        return ValidationResult(
            ok=False,
            cleaned_output=cleaned,
            reason=f"Output does not satisfy anchor requirements for {task.anchor.value}.",
        )

    if task.max_output_chars and len(cleaned) > task.max_output_chars:
        return ValidationResult(
            ok=False,
            cleaned_output=cleaned,
            reason=f"Output exceeds max_output_chars={task.max_output_chars}.",
        )

    deterministic = _run_validator_rule(task.validator_rule, cleaned)
    if deterministic is not None:
        return deterministic

    python_result = _validate_python_code(task, cleaned)
    if python_result is not None:
        return python_result

    return ValidationResult(ok=True, cleaned_output=cleaned, reason="")


def _run_validator_rule(rule: str | None, cleaned: str) -> ValidationResult | None:
    if not rule:
        return None

    if rule.startswith("contains:"):
        needle = rule.split(":", 1)[1]
        if needle not in cleaned:
            return ValidationResult(False, cleaned, f"Expected output to contain '{needle}'.")
        return ValidationResult(True, cleaned, "")

    if rule.startswith("regex:"):
        pattern = rule.split(":", 1)[1]
        if not re.search(pattern, cleaned, re.DOTALL):
            return ValidationResult(False, cleaned, f"Output does not match regex '{pattern}'.")
        return ValidationResult(True, cleaned, "")

    if rule.startswith("json_keys:"):
        expected_keys = [item.strip() for item in rule.split(":", 1)[1].split(",") if item.strip()]
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return ValidationResult(False, cleaned, "Output is not valid JSON for json_keys rule.")
        if not isinstance(data, dict):
            return ValidationResult(False, cleaned, "json_keys rule requires a JSON object.")
        missing = [key for key in expected_keys if key not in data]
        if missing:
            return ValidationResult(False, cleaned, f"JSON object missing keys: {missing}.")
        return ValidationResult(True, cleaned, "")

    return ValidationResult(False, cleaned, f"Unknown validator_rule '{rule}'.")


def _validate_python_code(task: MicroTask, cleaned: str) -> ValidationResult | None:
    if task.anchor != AnchorType.CODE:
        return None

    looks_python = any(
        token in cleaned for token in ("def ", "class ", "import ", "from ", "@", "return ")
    )
    if not looks_python:
        return None

    try:
        ast.parse(cleaned)
    except SyntaxError as exc:
        return ValidationResult(False, cleaned, f"Python syntax error: {exc.msg}.")

    return ValidationResult(True, cleaned, "")
