"""Tests for app.core.metrics: cycle time and cost computation."""

import networkx as nx

from app.core.metrics import compute_metrics
from app.core.parser import build_graph


def test_compute_metrics_on_real_process(as_is_process):
    g = build_graph(as_is_process)
    metrics = compute_metrics(g)
    assert metrics["cycle_time_minutes"] > 0
    assert metrics["cost"] >= 0


def test_compute_metrics_simple_linear_graph():
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node(1, kind="task", process_time=10, rework_time=0, waiting_time=0, raci=[])
    g.add_node("END", kind="end")
    g.add_edge("START", 1)
    g.add_edge(1, "END")

    metrics = compute_metrics(g)
    assert metrics == {"cycle_time_minutes": 10.0, "cost": 0.0}


def test_compute_metrics_parallel_gateway_takes_longest_branch_and_sums_cost():
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node("GW", kind="gateway", gateway_type="PARALLEL")
    g.add_node(1, kind="task", process_time=10, rework_time=0, waiting_time=0, raci=[])
    g.add_node(2, kind="task", process_time=30, rework_time=0, waiting_time=0, raci=[])
    g.add_node("END", kind="end")
    g.add_edge("START", "GW")
    g.add_edge("GW", 1)
    g.add_edge("GW", 2)
    g.add_edge(1, "END")
    g.add_edge(2, "END")

    metrics = compute_metrics(g)
    assert metrics["cycle_time_minutes"] == 30.0


def test_compute_metrics_exclusive_gateway_weights_by_probability():
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node("GW", kind="gateway", gateway_type="EXCLUSIVE")
    g.add_node(1, kind="task", process_time=10, rework_time=0, waiting_time=0, raci=[])
    g.add_node(2, kind="task", process_time=30, rework_time=0, waiting_time=0, raci=[])
    g.add_node("END", kind="end")
    g.add_edge("START", "GW")
    g.add_edge("GW", 1, probability=0.5)
    g.add_edge("GW", 2, probability=0.5)
    g.add_edge(1, "END")
    g.add_edge(2, "END")

    metrics = compute_metrics(g)
    assert metrics["cycle_time_minutes"] == 20.0
