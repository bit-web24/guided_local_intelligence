"""Runtime counters for per-model LLM call usage."""
from __future__ import annotations

from collections import defaultdict
from threading import Lock


_lock = Lock()
_model_call_counts: dict[str, int] = defaultdict(int)


def reset_model_call_counts() -> None:
    """Reset per-run model call counters."""
    with _lock:
        _model_call_counts.clear()


def record_model_call(model_name: str) -> None:
    """Increment the call count for a model name."""
    with _lock:
        _model_call_counts[model_name] += 1


def get_model_call_counts() -> dict[str, int]:
    """Return a snapshot of per-model call counts."""
    with _lock:
        return dict(sorted(_model_call_counts.items()))
