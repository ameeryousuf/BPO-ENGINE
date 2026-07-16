"""Tests for app.core.quantitative_analysis: the Chapter 7 quantitative
analysis suite (flow analysis, CTE, cost, resource utilization/Little's
Law) and the compare() before/after report.
"""

from pathlib import Path

import networkx as nx
import pytest

from app.core.parser import build_graph
from app.core.quantitative_analysis import (
    compare,
    cost_analysis,
    cycle_time_efficiency,
    flow_analysis,
    resolve_loops,
    resource_utilization,
    to_markdown,
)

DATA_DIR = Path(__file__).parent.parent / "data"
AS_IS_PROCESS_PATH = DATA_DIR / "asIsProcess.json"


# ---------------------------------------------------------------------------
# Ground-truth validation: these four numbers were hand-verified
# independently, so any mismatch here means a bug in this module.
# ---------------------------------------------------------------------------


def test_as_is_cycle_time_and_raw_cost_match_hand_verified_values(as_is_process):
    g = build_graph(as_is_process)
    flow = flow_analysis(g)
    assert flow["cycle_time_minutes"] == pytest.approx(1169.48)
    assert flow["cost_raw"] == pytest.approx(39815.14)


def test_compare_reproduces_hand_verified_before_after_numbers():
    report = compare(str(AS_IS_PROCESS_PATH), seed=42)
    a, b, imp = report["as_is_flow_analysis"], report["to_be_flow_analysis"], report["improvement"]

    assert a["cycle_time_minutes"] == pytest.approx(1169.48)
    assert b["cycle_time_minutes"] == pytest.approx(738.2)
    assert a["cost"] == pytest.approx(39815.14)
    assert b["cost"] == pytest.approx(23402.93)
    assert imp["cycle_time_percent"] == pytest.approx(36.88)
    assert imp["cost_percent"] == pytest.approx(41.22)


def test_compare_output_matches_json_contract_shape():
    report = compare(str(AS_IS_PROCESS_PATH), seed=42)

    assert set(report.keys()) == {
        "process_id", "process_code", "process_name",
        "as_is_flow_analysis", "to_be_flow_analysis", "improvement", "sequence", "to_be_process_json",
    }
    assert list(report["as_is_flow_analysis"].keys()) == list(report["to_be_flow_analysis"].keys())

    for analysis in (report["as_is_flow_analysis"], report["to_be_flow_analysis"]):
        for field in ("cycle_time_minutes", "cost", "cost_currency_normalized",
                      "cycle_time_efficiency_percent", "value_add_minutes",
                      "non_value_add_minutes", "avg_wip"):
            assert isinstance(analysis[field], (int, float))
        assert isinstance(analysis["resource_utilization"], list)
        assert set(analysis["bottleneck"].keys()) == {"job_id", "job_name", "utilization_percent"}

    assert isinstance(report["sequence"], list)
    for step in report["sequence"]:
        assert set(step.keys()) == {"heuristic_id", "applied", "step_order", "target", "description"}
        if step["applied"]:
            assert isinstance(step["target"], list)
            assert isinstance(step["step_order"], int)
        else:
            assert step["target"] is None
            assert step["step_order"] is None

    to_be = report["to_be_process_json"]
    assert "process_task" in to_be and "gateways" in to_be

    # No methodology/formula/FX metadata should leak into the output.
    dumped_keys = str(report.keys()) + str(report["as_is_flow_analysis"].keys())
    for leaked_term in ("pattern", "formula", "heuristic_technique", "fx_rate_table"):
        assert leaked_term not in dumped_keys.lower()


def test_compare_sequence_lists_every_registered_heuristic():
    from app.core.heuristics import HEURISTICS

    report = compare(str(AS_IS_PROCESS_PATH), seed=42)
    hids_present = {step["heuristic_id"] for step in report["sequence"]}
    assert hids_present == set(HEURISTICS.keys())

    applied_steps = [s for s in report["sequence"] if s["applied"]]
    not_applied_steps = [s for s in report["sequence"] if not s["applied"]]
    assert applied_steps  # the as-is process has at least one applicable, beneficial heuristic
    assert not_applied_steps  # and at least one heuristic that wasn't used

    step_orders = sorted(s["step_order"] for s in applied_steps)
    assert step_orders == list(range(1, len(applied_steps) + 1))

    for s in not_applied_steps:
        assert s["description"]  # explains why, even if just "no candidates"


def test_to_markdown_renders_without_error():
    report = compare(str(AS_IS_PROCESS_PATH), seed=42)
    md = to_markdown(report)
    assert "Cycle time (minutes)" in md
    assert "1169.48" in md


# ---------------------------------------------------------------------------
# Degenerate single-task process.
# ---------------------------------------------------------------------------


def test_flow_analysis_single_task_process():
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node(1, kind="task", process_time=30, rework_time=5, waiting_time=10,
               value_classification="VA", raci=[])
    g.add_node("END", kind="end")
    g.add_edge("START", 1)
    g.add_edge(1, "END")

    flow = flow_analysis(g)
    assert flow["cycle_time_minutes"] == 45.0
    assert flow["value_add_minutes"] == 45.0
    assert flow["non_value_add_minutes"] == 0.0
    assert flow["cost_raw"] == 0.0
    assert flow["cost_normalized"] == 0.0

    assert cycle_time_efficiency(flow) == 100.0


def test_single_task_process_has_no_resource_utilization_without_raci():
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node(1, kind="task", process_time=30, rework_time=0, waiting_time=0,
               value_classification="VA", raci=[], frequency_interval=1, frequency_period="WEEK", occurrences="1")
    g.add_node("END", kind="end")
    g.add_edge("START", 1)
    g.add_edge(1, "END")

    util = resource_utilization(g)
    assert util["resource_utilization"] == []
    assert util["bottleneck"] == {"job_id": None, "job_name": None, "utilization_percent": 0.0}


# ---------------------------------------------------------------------------
# Loop / rework structure: must not infinite-recurse, must apply the
# Repetition formula (CT = CT(single_pass) * 1/(1-p)).
# ---------------------------------------------------------------------------


def _looping_graph(loop_probability: float) -> nx.DiGraph:
    """Task A (20 min) -> Gateway: (1-p) exit to Task B (10 min) -> END, p loop back to A."""
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node("A", kind="task", process_time=20, rework_time=0, waiting_time=0,
               value_classification="VA", raci=[])
    g.add_node("GW", kind="gateway", gateway_type="EXCLUSIVE", branches=[
        {"target": "B", "probability": 1 - loop_probability, "condition": "ok"},
        {"target": "A", "probability": loop_probability, "condition": "retry"},
    ])
    g.add_node("B", kind="task", process_time=10, rework_time=0, waiting_time=0,
               value_classification="BVA", raci=[])
    g.add_node("END", kind="end")
    g.add_edge("START", "A")
    g.add_edge("A", "GW")
    g.add_edge("GW", "B", probability=1 - loop_probability)
    g.add_edge("GW", "A", probability=loop_probability)
    g.add_edge("B", "END")
    return g


def test_flow_analysis_applies_repetition_formula_for_a_back_edge():
    g = _looping_graph(loop_probability=0.3)
    flow = flow_analysis(g)
    expected_ct = 20 / (1 - 0.3) + 10
    assert flow["cycle_time_minutes"] == pytest.approx(expected_ct, abs=0.01)
    assert flow["value_add_minutes"] == pytest.approx(20 / (1 - 0.3), abs=0.01)


def test_resolve_loops_does_not_infinite_recurse_and_returns_acyclic_graph():
    g = _looping_graph(loop_probability=0.5)
    resolved = resolve_loops(g)
    assert nx.is_directed_acyclic_graph(resolved)


def test_loop_that_never_exits_raises_instead_of_dividing_by_zero():
    g = _looping_graph(loop_probability=1.0)
    with pytest.raises(ValueError):
        flow_analysis(g)


# ---------------------------------------------------------------------------
# Pattern sanity checks (Parallel sums cost/VA but maxes time; Conditional
# weights by probability) using the real fixture's cost/VA data.
# ---------------------------------------------------------------------------


def test_parallel_gateway_takes_longest_branch_but_sums_cost_and_va():
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node("GW", kind="gateway", gateway_type="PARALLEL")
    g.add_node(1, kind="task", process_time=10, rework_time=0, waiting_time=0,
               value_classification="VA", extra_cost=5.0, extra_cost_raw=5.0, raci=[])
    g.add_node(2, kind="task", process_time=30, rework_time=0, waiting_time=0,
               value_classification="VA", extra_cost=7.0, extra_cost_raw=7.0, raci=[])
    g.add_node("END", kind="end")
    g.add_edge("START", "GW")
    g.add_edge("GW", 1)
    g.add_edge("GW", 2)
    g.add_edge(1, "END")
    g.add_edge(2, "END")

    flow = flow_analysis(g)
    assert flow["cycle_time_minutes"] == 30.0
    assert flow["value_add_minutes"] == 40.0
    assert flow["cost_raw"] == pytest.approx(12.0)


def test_cost_analysis_matches_flow_analysis_cost_fields(as_is_process):
    g = build_graph(as_is_process)
    flow = flow_analysis(g)
    cost = cost_analysis(g)
    assert cost["cost_raw"] == flow["cost_raw"]
    assert cost["cost_normalized"] == flow["cost_normalized"]
