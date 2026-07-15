"""Tests for app.core.parser: validation and graph construction."""

import networkx as nx
import pytest

from app.core.parser import build_graph, validate_process_definition
from app.exceptions import InvalidProcessDefinitionError


def test_validate_rejects_non_dict():
    with pytest.raises(InvalidProcessDefinitionError):
        validate_process_definition(["not", "a", "dict"])


def test_validate_rejects_missing_process_task():
    with pytest.raises(InvalidProcessDefinitionError):
        validate_process_definition({"process_id": 1})


def test_validate_rejects_task_missing_task_id():
    with pytest.raises(InvalidProcessDefinitionError):
        validate_process_definition({"process_task": [{"task": {}}]})


def test_validate_accepts_well_formed_process(as_is_process):
    validate_process_definition(as_is_process)


def test_build_graph_produces_dag_with_start_and_end(as_is_process):
    g = build_graph(as_is_process)
    assert isinstance(g, nx.DiGraph)
    assert nx.is_directed_acyclic_graph(g)
    assert "START" in g.nodes
    assert "END" in g.nodes
    assert g.in_degree("START") == 0
    assert g.out_degree("END") == 0


def test_build_graph_every_task_reachable_from_start(as_is_process):
    g = build_graph(as_is_process)
    reachable = nx.descendants(g, "START") | {"START"}
    task_nodes = [n for n, k in g.nodes(data="kind") if k == "task"]
    assert set(task_nodes).issubset(reachable)
