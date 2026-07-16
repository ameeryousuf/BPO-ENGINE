"""Guards against a class of bug: a heuristic's generated step description
(``app.core.replay._describe_step``) claiming a field changed - "duration",
"processing time", "rework", "resource rate" - that its ``apply`` function
didn't actually touch, or vice versa.

For every registered heuristic, builds the smallest graph that satisfies
its candidate criteria, applies it, and checks the description's wording
against which of {process_time, rework_time, waiting_time, hourly_rate}
actually changed on the target node(s):

- "duration" implies all three time fields changed.
- "processing time" implies process_time changed and rework_time/
  waiting_time did not.
- "rework" implies rework_time changed and process_time/waiting_time did
  not.
- "rate" implies hourly_rate changed and no time field changed.

Heuristics whose description makes no such claim (activity_elimination,
activity_composition, parallelism, resequencing, centralization,
knockout - all describe a structural change, not a specific numeric field
change) are exercised too, but the keyword checks simply don't fire for
them; this is deliberate, since none of those claim a percentage.
"""

import networkx as nx
import pytest

from app.core.heuristics import HEURISTICS
from app.core.replay import _describe_step

TIME_FIELDS = ("process_time", "rework_time", "waiting_time")


_next_task_name = iter(f"Task {i}" for i in range(1, 1000))


def _task(**overrides) -> dict:
    base = dict(
        kind="task", task_name=next(_next_task_name), process_time=0, rework_time=0, waiting_time=0,
        value_classification="VA", extra_cost=0.0, extra_cost_raw=0.0, raci=[], automated=False,
    )
    base.update(overrides)
    return base


def _raci(role, job_name, rate=1000, raw_rate=None, pct=100):
    return {
        "role": role, "pct": pct, "job_name": job_name,
        "hourly_rate": rate, "raw_rate": raw_rate if raw_rate is not None else rate,
    }


def _changed_time_fields(g, g2, node) -> set:
    if node not in g2.nodes:
        return set()
    return {f for f in TIME_FIELDS if g.nodes[node].get(f) != g2.nodes[node].get(f)}


def _hourly_rate_changed(g, g2, node) -> bool:
    if node not in g2.nodes:
        return False
    before = [r.get("hourly_rate") for r in (g.nodes[node].get("raci") or [])]
    after = [r.get("hourly_rate") for r in (g2.nodes[node].get("raci") or [])]
    return before != after


def _task_nodes_in(g: nx.DiGraph, target: tuple) -> list:
    return [n for n in target if n in g.nodes and g.nodes[n].get("kind") == "task"]


def _assert_description_matches_actual_changes(hid: str, description: str, g: nx.DiGraph, g2: nx.DiGraph, target: tuple):
    desc = description.lower()
    for node in _task_nodes_in(g, target):
        changed_time = _changed_time_fields(g, g2, node)
        rate_changed = _hourly_rate_changed(g, g2, node)

        if "duration" in desc:
            assert changed_time == set(TIME_FIELDS), (
                f"{hid}: description claims 'duration' changed for {node!r} but only "
                f"{changed_time or 'nothing'} actually changed."
            )
        if "processing time" in desc:
            assert "process_time" in changed_time, (
                f"{hid}: description claims processing time changed for {node!r} but it didn't."
            )
            assert "rework_time" not in changed_time and "waiting_time" not in changed_time, (
                f"{hid}: description only claims processing time changed for {node!r}, "
                f"but rework/waiting also changed ({changed_time})."
            )
        if "rework" in desc:
            assert "rework_time" in changed_time, (
                f"{hid}: description claims rework changed for {node!r} but it didn't."
            )
            assert "process_time" not in changed_time and "waiting_time" not in changed_time, (
                f"{hid}: description only claims rework changed for {node!r}, "
                f"but process/waiting time also changed ({changed_time})."
            )
        if "rate" in desc:
            assert rate_changed, f"{hid}: description claims resource rate changed for {node!r} but it didn't."
            assert not changed_time, (
                f"{hid}: description only claims resource rate changed for {node!r}, "
                f"but a time field also changed ({changed_time})."
            )


def _linear_graph(*nodes: dict) -> nx.DiGraph:
    """START -> nodes[0] -> nodes[1] -> ... -> END, each nodes[i] a (id, attrs) pair."""
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node("END", kind="end")
    ids = [n[0] for n in nodes]
    for node_id, attrs in nodes:
        g.add_node(node_id, **attrs)
    g.add_edge("START", ids[0])
    for a, b in zip(ids, ids[1:]):
        g.add_edge(a, b)
    g.add_edge(ids[-1], "END")
    return g


def _build_automation_graph():
    return _linear_graph(
        (1, _task(process_time=10, raci=[_raci("R", "Alice")])),
        (2, _task(process_time=100, raci=[_raci("R", "Bob")])),
    ), (1,)


def _build_elimination_graph():
    return _linear_graph(
        (1, _task(value_classification="VA")),
        (2, _task(value_classification="NVA")),
        (3, _task(value_classification="VA")),
    ), (2,)


def _build_composition_graph():
    return _linear_graph(
        (1, _task(process_time=50, raci=[_raci("R", "Alice")])),
        (2, _task(process_time=60, raci=[_raci("R", "Alice")])),
    ), (1, 2)


def _build_parallelism_graph():
    return _linear_graph(
        (1, _task(process_time=50, raci=[_raci("R", "Alice")])),
        (2, _task(process_time=60, raci=[_raci("R", "Bob")])),
    ), (1, 2)


def _build_resequencing_graph():
    return _linear_graph(
        (1, _task(process_time=100)),
        (2, _task(process_time=10)),
    ), (1, 2)


def _build_extra_resources_graph():
    return _linear_graph(
        (1, _task(process_time=50, raci=[_raci("R", "Alice")])),
    ), (1,)


def _build_centralization_graph():
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node("END", kind="end")
    g.add_node(1, **_task(raci=[_raci("R", "Analyst A")]))
    g.add_node(2, **_task(raci=[_raci("R", "Analyst B")]))
    g.add_edge("START", 1)
    g.add_edge("START", 2)
    g.add_edge(1, "END")
    g.add_edge(2, "END")
    return g, (1, 2)


def _build_interfacing_graph():
    return _linear_graph(
        (1, _task(raci=[_raci("R", "Alice")])),
        (2, _task(rework_time=20, raci=[_raci("R", "Bob")])),
    ), (2,)


def _build_outsourcing_graph():
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node("END", kind="end")
    g.add_node(1, **_task(process_time=60, raci=[_raci("R", "Alice", rate=100)]))
    g.add_node(2, **_task(process_time=60, raci=[_raci("R", "Bob", rate=10000)]))
    g.add_edge("START", 1)
    g.add_edge("START", 2)
    g.add_edge(1, "END")
    g.add_edge(2, "END")
    return g, (2,)


def _build_knockout_graph():
    g = nx.DiGraph()
    g.add_node("START", kind="start")
    g.add_node("END", kind="end")
    g.add_node(1, **_task())
    g.add_node(2, **_task())
    g.add_node(3, **_task())
    g.add_node("GW1", kind="gateway", gateway_type="EXCLUSIVE", branches=[
        {"target": 2, "probability": 0.5, "condition": "go"},
        {"target": "END", "probability": 0.5, "condition": "stop"},
    ])
    g.add_node("GW2", kind="gateway", gateway_type="EXCLUSIVE", branches=[
        {"target": 3, "probability": 0.5, "condition": "go"},
        {"target": "END", "probability": 0.5, "condition": "stop"},
    ])
    g.add_edge("START", 1)
    g.add_edge(1, "GW1")
    g.add_edge("GW1", 2, probability=0.5)
    g.add_edge("GW1", "END", probability=0.5)
    g.add_edge(2, "GW2")
    g.add_edge("GW2", 3, probability=0.5)
    g.add_edge("GW2", "END", probability=0.5)
    g.add_edge(3, "END")
    return g, (1, "GW1", 2, "GW2")


BUILDERS = {
    "activity_automation": _build_automation_graph,
    "activity_elimination": _build_elimination_graph,
    "activity_composition": _build_composition_graph,
    "parallelism": _build_parallelism_graph,
    "resequencing": _build_resequencing_graph,
    "extra_resources": _build_extra_resources_graph,
    "centralization": _build_centralization_graph,
    "interfacing": _build_interfacing_graph,
    "outsourcing": _build_outsourcing_graph,
    "knockout": _build_knockout_graph,
}


def test_every_registered_heuristic_has_a_description_coverage_builder():
    assert set(BUILDERS.keys()) == set(HEURISTICS.keys())


@pytest.mark.parametrize("hid", sorted(BUILDERS.keys()))
def test_description_only_claims_fields_the_apply_function_actually_changed(hid):
    g, expected_target = BUILDERS[hid]()
    cand_fn, apply_fn = HEURISTICS[hid]

    candidates = list(cand_fn(g))
    assert expected_target in candidates, f"fixture for {hid} does not produce the expected candidate {expected_target}"

    g2 = apply_fn(g, expected_target)
    description = _describe_step(hid, expected_target, g)

    _assert_description_matches_actual_changes(hid, description, g, g2, expected_target)


def test_extra_resources_description_says_processing_time_not_duration():
    g, target = _build_extra_resources_graph()
    description = _describe_step("extra_resources", target, g)
    assert "processing time" in description.lower()
    assert "duration" not in description.lower()
