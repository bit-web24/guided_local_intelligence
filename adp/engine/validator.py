"""Output extraction and validation by anchor type."""
from __future__ import annotations

import json
import re

from adp.models.task import AnchorType


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
