"""Small disk-backed cache for deterministic local micro-task outputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from adp.config import TASK_CACHE_DIR
from adp.models.task import MicroTask


def build_task_cache_key(
    task: MicroTask,
    *,
    model_name: str,
    system_prompt: str,
    input_text: str,
) -> str:
    payload = {
        "task_id": task.id,
        "output_key": task.output_key,
        "model_name": model_name,
        "task_kind": task.task_kind.value,
        "model_type": task.model_type,
        "anchor": task.anchor.value,
        "validator_rule": task.validator_rule,
        "max_output_chars": task.max_output_chars,
        "system_prompt": system_prompt,
        "input_text": input_text,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_cached_output(cache_key: str) -> str | None:
    path = _cache_path(cache_key)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def save_cached_output(cache_key: str, output: str) -> None:
    path = _cache_path(cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output, encoding="utf-8")


def _cache_path(cache_key: str) -> Path:
    return Path(TASK_CACHE_DIR) / f"{cache_key}.txt"
