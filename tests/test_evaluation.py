"""Tests for adp/engine/evaluation.py."""
from adp.engine.evaluation import summarize_tasks
from adp.models.task import AnchorType, MicroTask, TaskKind, TaskStatus


def _task(task_id: str, kind: TaskKind, status: TaskStatus, retries: int = 0) -> MicroTask:
    return MicroTask(
        id=task_id,
        description=task_id,
        system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
        input_text="run",
        output_key=f"{task_id}_out",
        depends_on=[],
        anchor=AnchorType.OUTPUT,
        parallel_group=0,
        task_kind=kind,
        status=status,
        retries=retries,
    )


def test_summarize_tasks_builds_success_metrics():
    tasks = [
        _task("t1", TaskKind.EXTRACT, TaskStatus.DONE, retries=1),
        _task("t2", TaskKind.CODEGEN, TaskStatus.FAILED, retries=3),
        _task("t3", TaskKind.CODEGEN, TaskStatus.SKIPPED, retries=0),
    ]
    summary = summarize_tasks(tasks)
    assert summary.total_tasks == 3
    assert summary.completed_tasks == 1
    assert summary.failed_tasks == 1
    assert summary.skipped_tasks == 1
    assert summary.retries == 4
    assert summary.by_kind["codegen"]["total"] == 2
