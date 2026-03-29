"""Stage 3 — Assembler.

Sends all collected micro-task outputs to the large Ollama model with a
hardcoded assembly prompt. The model returns a JSON object mapping filenames
to their complete content.

The large model is called here exactly once per pipeline run.
The assembler does NOT generate new code — it only combines provided fragments.
"""
from __future__ import annotations

import re

from adp.engine.cloud_client import call_cloud_async
from adp.models.task import ContextDict, TaskPlan

# ---------------------------------------------------------------------------
# Hardcoded assembly system prompt — never configurable.
# ---------------------------------------------------------------------------
ASSEMBLER_SYSTEM_PROMPT = """\
You are a file assembler. You receive named code or text fragments that are parts of a
software project or document. Assemble them into complete, coherent, production-ready files.

RULES:
1. Output ONLY the assembled files using the delimiter format below. No prose. No explanation.
2. For EACH output file, use this exact format:

--- FILE: filename.ext ---
<complete file content here>
--- END FILE ---

3. File content must be complete and valid — not truncated, not shortened with ellipsis.
4. Combine code fragments in correct order: imports first, then models/types, then logic, then entry point.
5. Use ONLY content from the provided fragments. Do not invent additional logic.
6. If a fragment value is "[MISSING]", add a comment in the file noting it is missing.
7. Add all necessary imports at the top of each file based on what the code uses.

Fragments (key → content):
{fragments_text}
"""


class AssemblyError(Exception):
    """Raised when the large model returns malformed assembly output."""
    pass


async def assemble(plan: TaskPlan, context: ContextDict) -> dict[str, str]:
    """
    Collect all final_output_keys from context, send to large model,
    parse the returned file-delimited output into a {filename: content} dict.

    Uses --- FILE: name --- / --- END FILE --- delimiters instead of JSON
    to avoid truncation and escaping issues with large code files.
    """
    # Build fragments as readable text — no JSON escaping, no size inflation
    lines = []
    for key in plan.final_output_keys:
        value = context.get(key, "[MISSING]")
        lines.append(f"=== {key} ===")
        lines.append(value)
        lines.append("")
    fragments_text = "\n".join(lines)

    prompt = ASSEMBLER_SYSTEM_PROMPT.replace("{fragments_text}", fragments_text)

    raw = await call_cloud_async(
        system_prompt="",
        user_message=prompt,
        temperature=0.0,
        max_tokens=16384,
    )

    files = _parse_file_delimiters(raw, plan.output_filenames)

    if not files:
        raise AssemblyError(
            f"Assembler returned no parseable file blocks.\nRaw output: {raw[:500]}"
        )

    return files


def _parse_file_delimiters(raw: str, expected_filenames: list[str]) -> dict[str, str]:
    """
    Parse the file-delimiter format:
        --- FILE: filename.ext ---
        <content>
        --- END FILE ---

    If a file block is missing its END marker (truncation), we still extract
    the content up to the next FILE marker or end of string.
    """
    files: dict[str, str] = {}

    # Match complete blocks (with END FILE marker)
    pattern = re.compile(
        r"---\s*FILE:\s*(.+?)\s*---\n(.*?)(?=\n---\s*(?:FILE|END FILE)|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(raw):
        filename = match.group(1).strip()
        content = match.group(2).strip()
        # Strip trailing "--- END FILE ---" if captured
        content = re.sub(r"\n?---\s*END FILE\s*---\s*$", "", content).strip()
        if content:
            files[filename] = content

    # Fallback: if nothing parsed, try stripping markdown fences and use raw
    if not files and expected_filenames:
        clean = re.sub(r"```\w*\n?|\n?```", "", raw).strip()
        if clean and len(clean) > 20:
            # Best-effort: assign to first expected filename
            files[expected_filenames[0]] = clean

    return files


def assemble_sync(plan: TaskPlan, context: ContextDict) -> dict[str, str]:
    """Synchronous wrapper — use only outside an event loop (e.g. scripts/tests)."""
    import asyncio
    return asyncio.run(assemble(plan, context))
