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
2. For EACH output file, use this EXACT format with the EXACT filenames listed in OUTPUT FILES:

--- FILE: filename.ext ---
<complete file content here>
--- END FILE ---

3. File content must be complete and valid — not truncated, not shortened with ellipsis.
4. Combine code fragments in correct order: imports first, then models/types, then logic, then entry point.
5. Use ONLY content from the provided fragments. Do not invent additional logic.
6. If a fragment value is "[MISSING]", add a comment in the file noting it is missing.
7. Add all necessary imports at the top of each file based on what the code uses.
8. You MUST use the filenames EXACTLY as given in the OUTPUT FILES list — including any
   subdirectory prefix (e.g. "lib/main.py", NOT "main.py").

OUTPUT FILES (use these exact paths in the FILE delimiters):
{output_filenames_text}

Fragments (key → content):
{fragments_text}
"""

# ---------------------------------------------------------------------------
# Text-only assembly system prompt — used when write_to_file is False
# ---------------------------------------------------------------------------
TEXT_ASSEMBLER_SYSTEM_PROMPT = """\
You are an expert AI assistant. You receive named fragments derived from a multi-step reasoning
pipeline. Use these fragments to synthesize a single, coherent, comprehensive answer to the user's
original request.

RULES:
1. Provide ONLY your final response. No preamble, no meta-commentary.
2. Format your response cleanly using Markdown.
3. Integrate the facts, code, and insights from the fragments naturally.
4. Do NOT output file delimiters like `--- FILE: ... ---`. Just answer the user's request.

Fragments (key → content):
{fragments_text}
"""

class AssemblyError(Exception):
    """Raised when the large model returns malformed assembly output."""
    pass


async def assemble(
    plan: TaskPlan,
    context: ContextDict,
    user_prompt: str = ""
) -> dict[str, str]:
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

    if plan.write_to_file:
        output_filenames_text = "\n".join(f"  - {f}" for f in plan.output_filenames)
        sys_prompt = (
            ASSEMBLER_SYSTEM_PROMPT
            .replace("{fragments_text}", fragments_text)
            .replace("{output_filenames_text}", output_filenames_text)
        )
    else:
        # Include original user prompt context for the text assembler
        sys_prompt = TEXT_ASSEMBLER_SYSTEM_PROMPT.replace("{fragments_text}", fragments_text)
        sys_prompt += f"\n\nUser Request: {user_prompt}"

    raw = await call_cloud_async(
        system_prompt="",
        user_message=sys_prompt,
        temperature=0.0,
        max_tokens=16384,
        stage_name="assembler",
    )

    if not plan.write_to_file:
        return {"__stdout__": raw}

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

    After parsing, any filename that matches an expected filename only by
    basename (e.g. model returned "main.py" but plan expects "lib/main.py")
    is remapped to the full expected path, provided the match is unambiguous.
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

    # --- Basename fuzzy-match: remap bare filenames to full expected paths ---
    # Build a map: basename → full expected path (only unambiguous matches)
    from pathlib import Path as _Path
    basename_to_expected: dict[str, str] = {}
    for ef in expected_filenames:
        bn = _Path(ef).name
        if bn in basename_to_expected:
            # Ambiguous — two expected files share a basename; don't remap either
            basename_to_expected[bn] = ""  # sentinel
        else:
            basename_to_expected[bn] = ef

    remapped: dict[str, str] = {}
    for fname, content in files.items():
        if fname in expected_filenames:
            # Exact match — keep as-is
            remapped[fname] = content
        else:
            bn = _Path(fname).name
            full = basename_to_expected.get(bn, "")
            if full:  # non-empty sentinel → unambiguous match
                remapped[full] = content
            else:
                # No remap possible; keep original (verifier will report it)
                remapped[fname] = content

    return remapped


def assemble_sync(plan: TaskPlan, context: ContextDict, user_prompt: str = "") -> dict[str, str]:
    """Synchronous wrapper — use only outside an event loop (e.g. scripts/tests)."""
    import asyncio
    return asyncio.run(assemble(plan, context, user_prompt))
