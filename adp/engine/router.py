"""Task routing for local model execution."""
from __future__ import annotations

from adp.config import (
    DEFAULT_NUM_PREDICT,
    LOCAL_CODER_MODEL,
    LOCAL_CRITIC_MODEL,
    LOCAL_GENERAL_MODEL,
    LOCAL_REPAIR_MODEL,
)
from adp.models.task import MicroTask, TaskKind


def resolve_model_name(task: MicroTask, *, repair: bool = False) -> str:
    """Choose the best local model for a task."""
    if repair:
        return LOCAL_REPAIR_MODEL

    if task.task_kind == TaskKind.CRITIC:
        return LOCAL_CRITIC_MODEL

    if task.task_kind in {TaskKind.EXTRACT, TaskKind.CLASSIFY, TaskKind.SUMMARIZE}:
        return LOCAL_GENERAL_MODEL

    if task.model_type == "general":
        return LOCAL_GENERAL_MODEL

    return LOCAL_CODER_MODEL


def resolve_num_predict(task: MicroTask) -> int:
    """Cap generation size by task hints when present."""
    if task.max_output_chars:
        return min(DEFAULT_NUM_PREDICT, max(128, task.max_output_chars))
    return DEFAULT_NUM_PREDICT
