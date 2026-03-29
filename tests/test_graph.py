"""Tests for adp/engine/graph.py — dependency graph and topological sort."""
import pytest

from adp.engine.graph import build_execution_groups, get_downstream_ids
from adp.models.task import AnchorType, MicroTask, TaskStatus


def _make_task(id: str, depends_on: list[str], group: int) -> MicroTask:
    return MicroTask(
        id=id,
        description=f"Task {id}",
        system_prompt_template="EXAMPLES:\nInput: x\nOutput: y\n---\nInput: {input_text}\nOutput:",
        input_text="test",
        output_key=f"key_{id}",
        depends_on=depends_on,
        anchor=AnchorType.OUTPUT,
        parallel_group=group,
    )


class TestBuildExecutionGroups:
    def test_no_dependencies(self):
        tasks = [_make_task("t1", [], 0), _make_task("t2", [], 0)]
        groups = build_execution_groups(tasks)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_linear_chain(self):
        tasks = [
            _make_task("t1", [], 0),
            _make_task("t2", ["t1"], 1),
            _make_task("t3", ["t2"], 2),
        ]
        groups = build_execution_groups(tasks)
        assert len(groups) == 3
        assert groups[0][0].id == "t1"
        assert groups[1][0].id == "t2"
        assert groups[2][0].id == "t3"

    def test_parallel_and_sequential(self):
        tasks = [
            _make_task("t1", [], 0),
            _make_task("t2", [], 0),
            _make_task("t3", ["t1", "t2"], 1),
        ]
        groups = build_execution_groups(tasks)
        assert len(groups) == 2
        assert len(groups[0]) == 2  # t1, t2 in parallel
        assert len(groups[1]) == 1  # t3 alone

    def test_unknown_dependency_raises(self):
        tasks = [_make_task("t1", ["t999"], 1)]
        with pytest.raises(ValueError, match="unknown task id"):
            build_execution_groups(tasks)

    def test_cycle_detection_raises(self):
        tasks = [
            _make_task("t1", ["t2"], 1),
            _make_task("t2", ["t1"], 0),
        ]
        with pytest.raises(ValueError, match="cycle"):
            build_execution_groups(tasks)

    def test_invalid_group_assignment_raises(self):
        """t2 depends on t1 but has the same group — should raise."""
        tasks = [
            _make_task("t1", [], 0),
            _make_task("t2", ["t1"], 0),  # same group as dependency — invalid
        ]
        with pytest.raises(ValueError, match="strictly earlier group"):
            build_execution_groups(tasks)

    def test_empty_task_list(self):
        groups = build_execution_groups([])
        assert groups == []


class TestGetDownstreamIds:
    def test_direct_downstream(self):
        tasks = [
            _make_task("t1", [], 0),
            _make_task("t2", ["t1"], 1),
        ]
        result = get_downstream_ids("t1", tasks)
        assert "t2" in result

    def test_transitive_downstream(self):
        tasks = [
            _make_task("t1", [], 0),
            _make_task("t2", ["t1"], 1),
            _make_task("t3", ["t2"], 2),
        ]
        result = get_downstream_ids("t1", tasks)
        assert {"t2", "t3"} == result

    def test_no_downstream(self):
        tasks = [
            _make_task("t1", [], 0),
            _make_task("t2", [], 0),
        ]
        result = get_downstream_ids("t1", tasks)
        assert result == set()

    def test_unknown_id_returns_empty(self):
        tasks = [_make_task("t1", [], 0)]
        result = get_downstream_ids("t999", tasks)
        assert result == set()
