"""Runtime evaluation helpers for local micro-task execution."""
from __future__ import annotations

from collections import defaultdict

from adp.models.task import EvaluationSummary, MicroTask, TaskStatus


def summarize_tasks(tasks: list[MicroTask]) -> EvaluationSummary:
    total = len(tasks)
    completed = sum(task.status == TaskStatus.DONE for task in tasks)
    failed = sum(task.status == TaskStatus.FAILED for task in tasks)
    skipped = sum(task.status == TaskStatus.SKIPPED for task in tasks)
    retries = sum(task.retries for task in tasks)

    by_kind: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "done": 0, "failed": 0, "skipped": 0}
    )
    for task in tasks:
        bucket = by_kind[task.task_kind.value]
        bucket["total"] += 1
        if task.status == TaskStatus.DONE:
            bucket["done"] += 1
        elif task.status == TaskStatus.FAILED:
            bucket["failed"] += 1
        elif task.status == TaskStatus.SKIPPED:
            bucket["skipped"] += 1

    success_rate = (completed / total) if total else 0.0
    return EvaluationSummary(
        total_tasks=total,
        completed_tasks=completed,
        failed_tasks=failed,
        skipped_tasks=skipped,
        success_rate=success_rate,
        retries=retries,
        by_kind=dict(by_kind),
    )
