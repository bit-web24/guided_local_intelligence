"""Deterministic fast-path answers for simple prompts."""
from __future__ import annotations

import re
from datetime import datetime


_BLOCKLIST_TOKENS = (
    "file",
    "files",
    "write",
    "save",
    "generate",
    "create",
    "project",
    "code",
    "script",
    "api",
)

_TODAY_QUERY_RE = re.compile(
    r"\b(today|todays|today's)\b.*\b(day|date|weekday)\b|\b(what day is it|which day is it)\b",
    re.IGNORECASE,
)
_EXPLICIT_WEB_SEARCH_RE = re.compile(
    r"\b(search|web\s*search)\b.*\b(web|internet)\b|\bsearch the web\b|\bweb search\b",
    re.IGNORECASE,
)


def maybe_answer_simple_temporal_prompt(user_prompt: str) -> str | None:
    """Return a direct local-time answer for very simple day/date requests."""
    text = (user_prompt or "").strip()
    if not text:
        return None

    lowered = text.lower()
    if any(token in lowered for token in _BLOCKLIST_TOKENS):
        return None
    if _EXPLICIT_WEB_SEARCH_RE.search(text):
        return None
    if not _TODAY_QUERY_RE.search(text):
        return None

    now = datetime.now().astimezone()
    weekday = now.strftime("%A")
    month = now.strftime("%B")
    day = str(int(now.strftime("%d")))
    year = now.strftime("%Y")
    iso_date = now.strftime("%Y-%m-%d")
    return f"Today is {weekday}, {month} {day}, {year} ({iso_date})."
