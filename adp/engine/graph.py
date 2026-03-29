"""Dependency graph builder and topological sorter using networkx."""
from __future__ import annotations

import networkx as nx

from adp.models.task import MicroTask


def build_execution_groups(tasks: list[MicroTask]) -> list[list[MicroTask]]:
    """
    Build a list of parallel execution groups ordered by dependency.

    Group 0 runs first (no deps). Group N runs after group N-1 completes.
    Tasks in the same group run concurrently.

    Raises ValueError if:
    - a task depends on an unknown task id
    - the dependency graph contains a cycle
    - a task's parallel_group is not strictly greater than all its dependencies
    """
    G = nx.DiGraph()
    task_map: dict[str, MicroTask] = {t.id: t for t in tasks}

    for t in tasks:
        G.add_node(t.id)
        for dep in t.depends_on:
            if dep not in task_map:
                raise ValueError(
                    f"Task '{t.id}' depends on unknown task id '{dep}'"
                )
            G.add_edge(dep, t.id)

    if not nx.is_directed_acyclic_graph(G):
        cycles = list(nx.simple_cycles(G))
        raise ValueError(f"Dependency graph contains cycles: {cycles}")

    # Validate: each task's parallel_group must be strictly greater than all its deps
    for t in tasks:
        for dep_id in t.depends_on:
            dep = task_map[dep_id]
            if dep.parallel_group >= t.parallel_group:
                raise ValueError(
                    f"Task '{t.id}' (group {t.parallel_group}) depends on "
                    f"task '{dep_id}' (group {dep.parallel_group}). "
                    f"Dependency must be in a strictly earlier group."
                )

    groups: dict[int, list[MicroTask]] = {}
    for t in tasks:
        groups.setdefault(t.parallel_group, []).append(t)

    return [groups[k] for k in sorted(groups.keys())]


def get_downstream_ids(failed_id: str, tasks: list[MicroTask]) -> set[str]:
    """Return all task ids that depend on failed_id directly or transitively."""
    G = nx.DiGraph()
    for t in tasks:
        for dep in t.depends_on:
            G.add_edge(dep, t.id)
    if failed_id not in G:
        return set()
    return nx.descendants(G, failed_id)
