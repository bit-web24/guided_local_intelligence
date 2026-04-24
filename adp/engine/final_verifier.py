"""Verification for assembly inputs and final pipeline outputs."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from adp.config import get_model_config
from adp.engine.cloud_client import call_cloud_async
from adp.engine.local_client import call_local_async
from adp.models.task import ContextDict, TaskPlan, TaskStatus


class OutputVerificationError(ValueError):
    """Raised when assembled output cannot be trusted as structurally correct."""


FINAL_PROMPT_VERIFIER_PROMPT = """\
You are a strict final-output verifier.
You receive the original user request and the final files produced by the pipeline.
Determine whether the files actually satisfy the user's request.

Rules:
1. Reply ONLY with "PASS" or "FAIL — <one-line reason>".
2. PASS only if the files materially satisfy the request.
3. FAIL if files are missing key requested behavior, clearly off-topic, or contradict the request.
4. Be strict but practical. Minor style differences are acceptable.

User request:
{user_prompt}

Files:
{files_text}

Verdict:"""


def verify_execution_succeeded(plan: TaskPlan) -> None:
    """Ensure execution completed without failed or skipped tasks."""
    blocked = [
        f"{task.id} ({task.status.value}): {task.error or task.description}"
        for task in plan.tasks
        if task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED)
    ]
    if blocked:
        raise OutputVerificationError(
            "Execution did not complete successfully. "
            f"Blocked tasks: {blocked}"
        )


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


def verify_written_outputs(plan: TaskPlan, files: dict[str, str], output_dir: str) -> None:
    """Validate the actual on-disk outputs after the writer reports success."""
    if not plan.write_to_file:
        return

    base = Path(output_dir)
    for filename in plan.output_filenames:
        path = base / filename
        if not path.is_file():
            raise OutputVerificationError(
                f"Expected written file '{filename}' is missing on disk."
            )

        disk_content = path.read_text(encoding="utf-8")
        expected_content = files.get(filename)
        if expected_content is None:
            raise OutputVerificationError(
                f"Expected content for '{filename}' is missing from in-memory outputs."
            )
        if disk_content != expected_content:
            raise OutputVerificationError(
                f"Written file '{filename}' does not match the assembled content."
            )
        if not disk_content.strip():
            raise OutputVerificationError(
                f"Written file '{filename}' is empty on disk."
            )
        _verify_by_extension(filename, disk_content)


async def verify_files_match_user_prompt(
    user_prompt: str,
    plan: TaskPlan,
    files: dict[str, str],
) -> None:
    """Use the cloud verifier to check final files against the original prompt."""
    if not plan.write_to_file or not files:
        return

    files_text_parts: list[str] = []
    for filename in plan.output_filenames:
        files_text_parts.append(f"--- FILE: {filename} ---")
        files_text_parts.append(files.get(filename, "[MISSING]"))
        files_text_parts.append("--- END FILE ---")
        files_text_parts.append("")

    prompt = (
        FINAL_PROMPT_VERIFIER_PROMPT
        .replace("{user_prompt}", user_prompt)
        .replace("{files_text}", "\n".join(files_text_parts))
    )

    total_chars = sum(len(content) for content in files.values())
    extensions = {Path(name).suffix.lower() for name in plan.output_filenames}
    local_first = (
        len(plan.output_filenames) <= 2 and total_chars <= 12000
    )
    use_coder = any(
        ext in {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml", ".sql"}
        for ext in extensions
    )

    if local_first:
        try:
            raw = await call_local_async(
                system_prompt=prompt,
                input_text="Evaluate whether the final output satisfies the original request.",
                anchor_str="Verdict:",
                model_name=get_model_config().local_coder if use_coder else get_model_config().local_general,
                temperature_override=0.0,
                stage_name="final_prompt_verify:local_coder" if use_coder else "final_prompt_verify:local_general",
            )
        except Exception:
            raw = await call_cloud_async(
                system_prompt="",
                user_message=prompt,
                temperature=0.0,
                max_tokens=512,
                stage_name="final_prompt_verify",
            )
    else:
        raw = await call_cloud_async(
            system_prompt="",
            user_message=prompt,
            temperature=0.0,
            max_tokens=512,
            stage_name="final_prompt_verify",
        )
    verdict = raw.strip()
    if verdict.upper().startswith("PASS"):
        return
    if verdict.upper().startswith("FAIL"):
        raise OutputVerificationError(
            f"Final files do not satisfy the original prompt: {verdict}"
        )
    raise OutputVerificationError(
        f"Prompt verification returned an ambiguous verdict: {verdict[:200]}"
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
