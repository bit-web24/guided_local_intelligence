"""Verification for assembly inputs and final pipeline outputs."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from adp.models.task import ContextDict, TaskPlan


class OutputVerificationError(ValueError):
    """Raised when assembled output cannot be trusted as structurally correct."""


def verify_assembly_inputs(plan: TaskPlan, context: ContextDict) -> None:
    """Ensure the assembler receives all required fragments."""
    missing = sorted(
        key for key in plan.final_output_keys
        if key not in context or not str(context[key]).strip()
    )
    if missing:
        raise OutputVerificationError(
            f"Missing final fragments for assembly: {missing}"
        )


def verify_final_outputs(plan: TaskPlan, files: dict[str, str]) -> None:
    """Validate final assembled outputs before they are written to disk."""
    if plan.write_to_file:
        _verify_output_files(plan, files)
        return

    stdout_text = files.get("__stdout__", "").strip()
    if not stdout_text:
        raise OutputVerificationError("Text-mode output is empty.")
    if "--- FILE:" in stdout_text:
        raise OutputVerificationError(
            "Text-mode output incorrectly contains file delimiters."
        )


def _verify_output_files(plan: TaskPlan, files: dict[str, str]) -> None:
    expected = set(plan.output_filenames)
    actual = set(files)

    missing = sorted(expected - actual)
    if missing:
        raise OutputVerificationError(
            f"Assembler did not return all expected files: {missing}"
        )

    unexpected = sorted(actual - expected)
    if unexpected:
        raise OutputVerificationError(
            f"Assembler returned unexpected files: {unexpected}"
        )

    for filename in plan.output_filenames:
        content = files[filename]
        if not content.strip():
            raise OutputVerificationError(f"Output file '{filename}' is empty.")
        if "[MISSING]" in content:
            raise OutputVerificationError(
                f"Output file '{filename}' still contains '[MISSING]'."
            )
        _verify_by_extension(filename, content)


def _verify_by_extension(filename: str, content: str) -> None:
    suffix = Path(filename).suffix.lower()

    if suffix == ".py":
        try:
            ast.parse(content, filename=filename)
        except SyntaxError as exc:
            raise OutputVerificationError(
                f"Python syntax verification failed for '{filename}': {exc}"
            ) from exc
        return

    if suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise OutputVerificationError(
                f"JSON verification failed for '{filename}': {exc}"
            ) from exc
        return

    if suffix == ".toml":
        try:
            import tomllib

            tomllib.loads(content)
        except Exception as exc:
            raise OutputVerificationError(
                f"TOML verification failed for '{filename}': {exc}"
            ) from exc
