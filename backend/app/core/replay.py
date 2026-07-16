"""Replays a trained heuristic sequence and serializes the resulting graph.

Training explores many episodes and only tracks the best sequence of
(heuristic_id, target) actions plus the metrics that resulted from it.
``replay_sequence`` re-applies that exact sequence to a fresh copy of the
baseline graph to reconstruct the final graph (skipping any step that
would introduce a cycle, mirroring the environment's own safety check),
and ``serialize_graph`` turns that graph back into the original JSON shape.
"""

import copy
from itertools import count
from typing import Tuple

import networkx as nx

from app.core.heuristics import (
    AUTOMATION_TIME_CUT,
    EXTRA_RESOURCE_TIME_CUT,
    HEURISTICS,
    INTERFACE_REWORK_CUT,
    OUTSOURCE_RATE_CUT,
)


def _describe_step(hid: str, target: tuple, g: nx.DiGraph) -> str:
    names = {n: g.nodes[n].get("task_name") for n in target if g.nodes[n].get("kind") == "task"}
    if hid == "activity_elimination":
        (n,) = target
        return f"Eliminated non-value-adding task '{names[n]}'."
    if hid == "activity_automation":
        (n,) = target
        return f"Automated task '{names[n]}', cutting its processing time by {int(AUTOMATION_TIME_CUT * 100)}%."
    if hid == "activity_composition":
        n, m = target
        return f"Merged tasks '{names[n]}' and '{names[m]}' into a single combined step."
    if hid == "parallelism":
        n, m = target
        return f"Parallelized '{names[n]}' and '{names[m]}' so they run concurrently instead of sequentially."
    if hid == "resequencing":
        n, m = target
        return f"Resequenced '{names[m]}' ahead of '{names[n]}' since it is the shorter task."
    if hid == "extra_resources":
        (n,) = target
        return (
            f"Added extra resources to bottleneck task '{names[n]}', cutting its processing time "
            f"by {int(EXTRA_RESOURCE_TIME_CUT * 100)}%."
        )
    if hid == "centralization":
        return f"Centralized responsibility for {', '.join(names[n] for n in target)} under a single role."
    if hid == "knockout":
        t1, _gw1, t2, _gw2 = target
        return f"Reordered checkpoints so '{names[t2]}' is evaluated before '{names[t1]}' (knock-out reordering)."
    if hid == "interfacing":
        (n,) = target
        return f"Reduced handoff rework on task '{names[n]}' by {int(INTERFACE_REWORK_CUT * 100)}%."
    if hid == "outsourcing":
        (n,) = target
        return f"Outsourced task '{names[n]}', cutting its resource rate by {int(OUTSOURCE_RATE_CUT * 100)}%."
    return f"{hid} -> {target}"


def replay_sequence(baseline_graph: nx.DiGraph, sequence: list) -> Tuple[nx.DiGraph, list]:
    """Re-apply a trained action sequence to a fresh copy of the baseline graph."""
    graph = copy.deepcopy(baseline_graph)
    steps = []
    for hid, target in sequence:
        _, apply_fn = HEURISTICS[hid]
        candidate_graph = apply_fn(graph, target)
        if not nx.is_directed_acyclic_graph(candidate_graph):
            continue
        description = _describe_step(hid, target, graph)
        graph = candidate_graph
        steps.append({"heuristic_id": hid, "target": target, "description": description})
    return graph, steps


def _task_visitation_order(g: nx.DiGraph) -> list:
    visited = set()
    order = []

    def visit(node):
        if node in visited:
            return
        visited.add(node)
        if g.nodes[node].get("kind") == "task":
            order.append(node)
        for _, v in g.out_edges(node):
            visit(v)

    visit("START")
    return order


def _serialize_task(node_id, g: nx.DiGraph, task_lookup: dict, order_index: int) -> dict:
    attrs = g.nodes[node_id]
    pt = copy.deepcopy(task_lookup[node_id])
    pt["order"] = order_index
    pt["value_classification"] = attrs.get("value_classification")

    task = pt["task"]
    task["task_name"] = attrs.get("task_name")
    task["expected_process_time"] = attrs.get("process_time")
    task["expected_rework_time"] = attrs.get("rework_time")
    task["expected_waiting_time"] = attrs.get("waiting_time")
    task["extra_cost"] = attrs.get("extra_cost") or 0.0

    original_job_tasks = task.get("jobTasks") or []
    node_raci = attrs.get("raci") or []
    job_tasks = []
    for orig_jt, raci_entry in zip(original_job_tasks, node_raci):
        jt = copy.deepcopy(orig_jt)
        jt["role"] = raci_entry.get("role")
        jt["time_allocation_percentage"] = str(raci_entry.get("pct"))
        jt["job"]["name"] = raci_entry.get("job_name")
        jt["job"]["hourlyRate"] = raci_entry.get("hourly_rate")
        # raci hourly_rate is always PKR-normalized by build_graph (see
        # app.core.fx), so the serialized job must say so too - otherwise
        # resubmitting this output would double-convert the rate.
        jt["job"]["currencyType"] = "PKR"
        job_tasks.append(jt)
    task["jobTasks"] = job_tasks

    return pt


def _serialize_gateways(g: nx.DiGraph, gateway_lookup: dict, process_id) -> list:
    gateway_nodes = [n for n, k in g.nodes(data="kind") if k == "gateway"]
    existing_ids = [n for n in g.nodes if isinstance(n, int)] + list(gateway_lookup.keys())
    counter = count(max(existing_ids, default=0) + 1)
    id_map = {n: (n if isinstance(n, int) else next(counter)) for n in gateway_nodes}

    gateways = []
    for n in gateway_nodes:
        attrs = g.nodes[n]
        gid = id_map[n]
        original = gateway_lookup.get(n)
        gw = copy.deepcopy(original) if original is not None else {}
        gw["gateway_pk_id"] = gid
        gw["process_id"] = process_id
        gw["gateway_type"] = attrs.get("gateway_type")
        gw["name"] = attrs.get("name")

        preds = list(g.predecessors(n))
        pred = preds[0] if preds else None
        pred_kind = g.nodes[pred].get("kind") if pred is not None else None
        gw["after_task_id"] = pred if pred_kind == "task" else None
        gw["after_gateway_id"] = id_map[pred] if pred_kind == "gateway" else None

        node_branches = attrs.get("branches")
        if node_branches is not None:
            # Explicit branch list is the source of truth: it preserves
            # sibling branches even when two of them target the same node
            # (e.g. two conditions both leading straight to END), which a
            # plain DiGraph edge cannot represent since it allows only one
            # edge per (source, target) pair.
            targets = [(b["target"], b.get("condition"), b.get("probability")) for b in node_branches]
        else:
            targets = [(v, edata.get("condition"), edata.get("probability"))
                       for _, v, edata in g.out_edges(n, data=True)]

        branches = []
        for target, condition, probability in targets:
            target_kind = g.nodes[target].get("kind")
            branches.append({
                "id": None,
                "gateway_pk_id": gid,
                "is_default": False,
                "target_task_id": target if target_kind == "task" else None,
                "target_gateway_id": id_map[target] if target_kind == "gateway" else None,
                "condition": condition,
                "end_event_name": None,
                "end_task_id": None,
                "connect_to_end": True,
                "probability": probability,
            })
        gw["branches"] = branches
        gateways.append(gw)
    return gateways


def serialize_graph(g: nx.DiGraph, original_data: dict) -> dict:
    """Serialize a (possibly redesigned) graph back into the original process JSON shape."""
    task_lookup = {pt["task_id"]: pt for pt in original_data["process_task"]}
    gateway_lookup = {gw["gateway_pk_id"]: gw for gw in original_data.get("gateways", [])}

    task_order = _task_visitation_order(g)
    process_task = [
        _serialize_task(n, g, task_lookup, i + 1) for i, n in enumerate(task_order)
    ]
    gateways = _serialize_gateways(g, gateway_lookup, original_data.get("process_id"))

    result = copy.deepcopy(original_data)
    result["process_task"] = process_task
    result["gateways"] = gateways
    return result
