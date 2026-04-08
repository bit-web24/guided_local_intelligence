"""Session-scoped MCP tool-call logging."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


_LOG_LOCK = Lock()
_DEFAULT_LOG_PATH = Path.cwd() / "tool_calls.log"


def reset_tool_call_log(log_path: Path | None = None) -> str:
    """Overwrite the tool-call log file for the current prompt run."""
    target = (log_path or _DEFAULT_LOG_PATH).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK:
        target.write_text("", encoding="utf-8")
    return str(target)


def append_tool_call_log(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    output: str | None = None,
    error: str | None = None,
    log_path: Path | None = None,
) -> None:
    """Append a single MCP tool invocation record as one JSONL line."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "input": arguments,
        "ok": error is None,
    }
    if error is not None:
        record["error"] = error
    else:
        record["output"] = output or ""

    target = (log_path or _DEFAULT_LOG_PATH).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
