"""Runtime counters for per-model and per-stage LLM call usage."""
from __future__ import annotations

from collections import defaultdict
from threading import Lock


_lock = Lock()
_model_call_counts: dict[str, int] = defaultdict(int)
_stage_model_call_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


def reset_model_call_counts() -> None:
    """Reset per-run model call counters."""
    with _lock:
        _model_call_counts.clear()
        _stage_model_call_counts.clear()


def record_model_call(model_name: str, stage_name: str = "unknown") -> None:
    """Increment the call count for a model and stage name."""
    with _lock:
        _model_call_counts[model_name] += 1
        _stage_model_call_counts[stage_name][model_name] += 1


def get_model_call_counts() -> dict[str, int]:
    """Return a snapshot of per-model call counts."""
    with _lock:
        return dict(sorted(_model_call_counts.items()))


def get_stage_model_call_counts() -> dict[str, dict[str, int]]:
    """Return a snapshot of per-stage per-model call counts."""
    with _lock:
        return {
            stage_name: dict(sorted(model_counts.items()))
            for stage_name, model_counts in sorted(_stage_model_call_counts.items())
        }
