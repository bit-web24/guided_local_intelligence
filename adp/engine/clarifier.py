"""Pre-decomposition prompt clarification using hybrid local/cloud micro-tasks."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from adp.config import CLARIFICATION_MAX_ROUNDS, get_model_config
from adp.engine.cloud_client import call_cloud_async
from adp.engine.local_client import call_local_async
from adp.engine.validator import extract_after_anchor, validate
from adp.models.task import AnchorType


CLARIFY_NEED_PROMPT = """\
You are an ambiguity detector for a local-first agent pipeline.
Decide ONLY whether the user's request still needs one clarification answer before planning.

Return ONLY JSON in this exact shape:
{"needs_clarification":true,"reason_label":"short_label"}
or
{"needs_clarification":false,"reason_label":"enough_information"}

Rules:
1. Decide only whether clarification is needed.
2. Ask for clarification only if the missing answer would materially change the workflow, tools, files, or success criteria.
3. Do not generate the question here.
4. Keep reason_label short and machine-friendly.

EXAMPLES:
Conversation:
User: Search the web for quantization in LLMs and write it to a file.
JSON: {"needs_clarification":true,"reason_label":"missing_output_filename"}

Conversation:
User: Search the web for quantization in LLMs and write it to info/quantization.md
JSON: {"needs_clarification":false,"reason_label":"enough_information"}

Conversation:
User: Fix my config
JSON: {"needs_clarification":true,"reason_label":"missing_target_config"}

Conversation:
User: Fix pyproject.toml in the current project so pytest runs
JSON: {"needs_clarification":false,"reason_label":"enough_information"}
"""


CLARIFY_QUESTION_PROMPT = """\
You are a clarification-question generator for a local-first agent pipeline.
Generate EXACTLY ONE short, concrete question to resolve the specified ambiguity.

Return ONLY JSON in this exact shape:
{"question":"one short question"}

Rules:
1. Ask only one question.
2. Make it concrete and workflow-changing.
3. Do not ask broad preference questions unless necessary.
4. Do not explain why you are asking.

EXAMPLES:
Reason: missing_output_filename
Conversation:
User: Search the web for quantization in LLMs and write it to a file.
JSON: {"question":"What filename should I use for the output file?"}

Reason: missing_target_config
Conversation:
User: Fix my config
JSON: {"question":"Which config file or project path should I inspect?"}
"""


CLARIFY_MERGE_PROMPT = """\
You are a prompt consolidator for a local-first agent pipeline.
Rewrite the original request using the user's clarification answers so the planner receives one clear, actionable prompt.

Return ONLY JSON in this exact shape:
{"clarified_prompt":"fully clarified task request ready for planning"}

Rules:
1. Rewrite the prompt only.
2. Preserve the user's intent exactly.
3. Include clarification answers directly in the final prompt.
4. Do not add extra goals or assumptions.

EXAMPLES:
Conversation:
User: Search the web for quantization in LLMs and write it to a file.
Clarifier question: What filename should I use for the output file?
User answer: Use info/quantization.md
JSON: {"clarified_prompt":"Search the web for quantization in LLMs and write the gathered content into the file info/quantization.md."}

Conversation:
User: Fix my config
Clarifier question: Which config file or project path should I inspect?
User answer: pyproject.toml in the current project
JSON: {"clarified_prompt":"Inspect and fix pyproject.toml in the current project."}
"""


CLARIFY_REVISE_PROMPT = """\
You are a prompt reviser for a local-first agent pipeline.
You receive the current clarified prompt and one extra user refinement.
Rewrite the prompt so it cleanly includes that refinement.

Return ONLY JSON in this exact shape:
{"clarified_prompt":"revised prompt ready for planning"}

Rules:
1. Preserve the current task intent.
2. Incorporate the new refinement exactly where relevant.
3. Return one clean rephrased prompt only.
4. Do not add new goals or assumptions.

EXAMPLES:
Current prompt:
Search the web for quantization in LLMs and write the content into info/quantization.md.
User refinement:
Make it a markdown file with headings.
JSON: {"clarified_prompt":"Search the web for quantization in LLMs, write the gathered content with clear markdown headings, and write it into info/quantization.md."}
"""


@dataclass(frozen=True)
class ClarificationResult:
    clarified_prompt: str
    clarification_turns_used: int


def _build_conversation_text(initial_prompt: str, qa_pairs: list[tuple[str, str]]) -> str:
    lines = [f"User: {initial_prompt}"]
    for question, answer in qa_pairs:
        lines.append(f"Clarifier question: {question}")
        lines.append(f"User answer: {answer}")
    return "\n".join(lines)


async def _call_json_step(
    *,
    system_prompt: str,
    input_text: str,
    stage_name: str,
) -> dict:
    raw = await call_local_async(
        system_prompt=system_prompt,
        input_text=input_text,
        anchor_str=AnchorType.JSON.value,
        model_name=get_model_config().local_general,
        stage_name=stage_name,
    )
    extracted = extract_after_anchor(raw, AnchorType.JSON)
    is_valid, cleaned = validate(extracted, AnchorType.JSON)
    if not is_valid:
        raise ValueError(f"{stage_name} returned invalid JSON.")
    return json.loads(cleaned)


async def _call_cloud_json_step(
    *,
    system_prompt: str,
    input_text: str,
    stage_name: str,
) -> dict:
    raw = await call_cloud_async(
        system_prompt=system_prompt,
        user_message=f"Input: {input_text}\n{AnchorType.JSON.value}",
        temperature=0.0,
        max_tokens=1024,
        stage_name=stage_name,
    )
    extracted = extract_after_anchor(raw, AnchorType.JSON)
    is_valid, cleaned = validate(extracted, AnchorType.JSON)
    if not is_valid:
        raise ValueError(f"{stage_name} returned invalid JSON.")
    return json.loads(cleaned)


async def _detect_clarification_need(
    initial_prompt: str,
    qa_pairs: list[tuple[str, str]],
    force_proceed: bool,
) -> dict:
    if force_proceed:
        return {"needs_clarification": False, "reason_label": "clarification_limit_reached"}

    conversation_text = _build_conversation_text(initial_prompt, qa_pairs)
    instruction = (
        "Return needs_clarification=false now because the clarification limit was reached."
        if force_proceed
        else "Decide whether one clarification is still needed."
    )
    try:
        data = await _call_json_step(
            system_prompt=f"{CLARIFY_NEED_PROMPT}\n\nConversation so far:\n{conversation_text}",
            input_text=instruction,
            stage_name="clarifier:detect",
        )
    except Exception:
        return {"needs_clarification": False, "reason_label": "detect_failed"}

    if not isinstance(data, dict):
        return {"needs_clarification": False, "reason_label": "detect_invalid_shape"}

    raw_flag = data.get("needs_clarification")
    if isinstance(raw_flag, bool):
        needs_clarification = raw_flag
    elif isinstance(raw_flag, str):
        lowered = raw_flag.strip().lower()
        if lowered in {"true", "yes", "1"}:
            needs_clarification = True
        elif lowered in {"false", "no", "0"}:
            needs_clarification = False
        else:
            needs_clarification = False
    else:
        needs_clarification = False

    reason_label = str(data.get("reason_label", "")).strip() or "enough_information"
    return {
        "needs_clarification": needs_clarification,
        "reason_label": reason_label,
    }


async def _generate_clarification_question(
    initial_prompt: str,
    qa_pairs: list[tuple[str, str]],
    reason_label: str,
) -> str:
    conversation_text = _build_conversation_text(initial_prompt, qa_pairs)
    data = await _call_json_step(
        system_prompt=(
            f"{CLARIFY_QUESTION_PROMPT}\n\n"
            f"Reason: {reason_label}\n\n"
            f"Conversation so far:\n{conversation_text}"
        ),
        input_text="Return one clarification question.",
        stage_name="clarifier:question",
    )
    question = str(data.get("question", "")).strip()
    if not question:
        raise ValueError("clarifier:question returned no question.")
    return question


async def _merge_clarified_prompt(
    initial_prompt: str,
    qa_pairs: list[tuple[str, str]],
) -> str:
    conversation_text = _build_conversation_text(initial_prompt, qa_pairs)
    data = await _call_cloud_json_step(
        system_prompt=f"{CLARIFY_MERGE_PROMPT}\n\nConversation so far:\n{conversation_text}",
        input_text="Return the final clarified prompt.",
        stage_name="clarifier:merge",
    )
    clarified_prompt = str(data.get("clarified_prompt", "")).strip()
    if not clarified_prompt:
        raise ValueError("clarifier:merge returned no clarified_prompt.")
    return clarified_prompt


async def revise_clarified_prompt_async(
    clarified_prompt: str,
    user_refinement: str,
) -> str:
    """Rephrase a clarified prompt by incorporating one extra user refinement."""
    try:
        data = await _call_cloud_json_step(
            system_prompt=(
                f"{CLARIFY_REVISE_PROMPT}\n\n"
                f"Current prompt:\n{clarified_prompt}\n\n"
                f"User refinement:\n{user_refinement}"
            ),
            input_text="Return the revised clarified prompt.",
            stage_name="clarifier:revise",
        )
        revised_prompt = str(data.get("clarified_prompt", "")).strip()
        if _is_usable_revised_prompt(
            source_prompt=clarified_prompt,
            user_refinement=user_refinement,
            revised_prompt=revised_prompt,
        ):
            return revised_prompt
    except Exception:
        pass

    return _fallback_revise_prompt(clarified_prompt, user_refinement)


def _fallback_revise_prompt(clarified_prompt: str, user_refinement: str) -> str:
    """Deterministically preserve the current prompt when model revise output is unusable."""
    base = clarified_prompt.strip().rstrip()
    refinement = user_refinement.strip()
    if not refinement:
        return base
    if not base:
        return refinement
    if base.endswith((".", "!", "?")):
        return f"{base} Additional requirement: {refinement}"
    return f"{base}. Additional requirement: {refinement}"


def _is_usable_revised_prompt(
    *,
    source_prompt: str,
    user_refinement: str,
    revised_prompt: str,
) -> bool:
    candidate = revised_prompt.strip()
    if not candidate:
        return False

    lower = candidate.lower()
    if any(
        phrase in lower
        for phrase in (
            "i'm sorry",
            "i am sorry",
            "could you please provide",
            "please provide those details",
            "i need the current clarified prompt",
            "in order to rewrite it",
        )
    ):
        return False

    source_tokens = _meaningful_tokens(source_prompt)
    refinement_tokens = _meaningful_tokens(user_refinement)
    candidate_tokens = _meaningful_tokens(candidate)

    if source_tokens and len(source_tokens & candidate_tokens) < min(2, len(source_tokens)):
        return False
    if refinement_tokens and not (refinement_tokens & candidate_tokens):
        return False

    return True


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_./-]+", text.lower())
        if len(token) >= 3 and token not in {"the", "and", "with", "into", "write", "file", "files"}
    }


async def clarify_prompt_async(
    initial_prompt: str,
    ask_user: Callable[[str, int], Awaitable[str | None]],
    announce: Callable[[str], None] | None = None,
    max_rounds: int = CLARIFICATION_MAX_ROUNDS,
) -> ClarificationResult | None:
    """Clarify the prompt with at most max_rounds user answers before proceeding."""
    qa_pairs: list[tuple[str, str]] = []
    turns_used = 0

    for round_index in range(max_rounds + 1):
        need = await _detect_clarification_need(
            initial_prompt,
            qa_pairs,
            force_proceed=round_index >= max_rounds,
        )
        if not bool(need.get("needs_clarification", False)):
            if not qa_pairs:
                return ClarificationResult(
                    clarified_prompt=initial_prompt,
                    clarification_turns_used=turns_used,
                )
            return ClarificationResult(
                clarified_prompt=await _merge_clarified_prompt(initial_prompt, qa_pairs),
                clarification_turns_used=turns_used,
            )

        reason_label = str(need.get("reason_label", "")).strip() or "missing_information"
        question = await _generate_clarification_question(initial_prompt, qa_pairs, reason_label)
        if announce is not None:
            announce(f"Clarification {round_index + 1}/{max_rounds}: {question}")
        answer = await ask_user(question, round_index + 1)
        if answer is None:
            return None
        answer = answer.strip()
        if not answer:
            return ClarificationResult(
                clarified_prompt=initial_prompt,
                clarification_turns_used=turns_used,
            )
        turns_used += 1
        qa_pairs.append((question, answer))

    if not qa_pairs:
        return ClarificationResult(
            clarified_prompt=initial_prompt,
            clarification_turns_used=turns_used,
        )
    return ClarificationResult(
        clarified_prompt=await _merge_clarified_prompt(initial_prompt, qa_pairs),
        clarification_turns_used=turns_used,
    )


def detect_clarification_need_sync(
    initial_prompt: str,
    qa_pairs: list[tuple[str, str]],
    force_proceed: bool = False,
) -> dict:
    import anyio

    return anyio.run(
        _detect_clarification_need,
        initial_prompt,
        qa_pairs,
        force_proceed,
        backend="asyncio",
    )


def generate_clarification_question_sync(
    initial_prompt: str,
    qa_pairs: list[tuple[str, str]],
    reason_label: str,
) -> str:
    import anyio

    return anyio.run(
        _generate_clarification_question,
        initial_prompt,
        qa_pairs,
        reason_label,
        backend="asyncio",
    )


def merge_clarified_prompt_sync(
    initial_prompt: str,
    qa_pairs: list[tuple[str, str]],
) -> str:
    import anyio

    return anyio.run(
        _merge_clarified_prompt,
        initial_prompt,
        qa_pairs,
        backend="asyncio",
    )


def revise_clarified_prompt_sync(
    clarified_prompt: str,
    user_refinement: str,
) -> str:
    import anyio

    return anyio.run(
        revise_clarified_prompt_async,
        clarified_prompt,
        user_refinement,
        backend="asyncio",
    )
