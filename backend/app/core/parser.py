"""Parsing and validation of BPMN process JSON into a directed graph.

The graph representation is the common substrate consumed by every other
core module (metrics, heuristics, the RL environment, and replay).
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import networkx as nx

from app.exceptions import InvalidProcessDefinitionError

logger = logging.getLogger(__name__)


def load_process(json_path: "str | Path") -> dict:
    """Load a process definition from a JSON file on disk.

    Intended for CLI/test use against fixture files; the API operates on
    already-parsed dicts and does not touch the filesystem.
    """
    with open(json_path, "r") as f:
        return json.load(f)


def validate_process_definition(data: Any) -> None:
    """Validate that ``data`` has the minimal shape required to build a graph.

    Raises ``InvalidProcessDefinitionError`` with a human-readable message
    describing the first problem found.
    """
    if not isinstance(data, dict):
        raise InvalidProcessDefinitionError("Process definition must be a JSON object.")

    tasks = data.get("process_task")
    if not isinstance(tasks, list) or len(tasks) == 0:
        raise InvalidProcessDefinitionError("Process definition must contain a non-empty 'process_task' list.")

    for i, pt in enumerate(tasks):
        if not isinstance(pt, dict):
            raise InvalidProcessDefinitionError(f"process_task[{i}] must be an object.")
        if "task_id" not in pt:
            raise InvalidProcessDefinitionError(f"process_task[{i}] is missing required field 'task_id'.")
        if not isinstance(pt.get("task"), dict):
            raise InvalidProcessDefinitionError(f"process_task[{i}] is missing required object field 'task'.")

    gateways = data.get("gateways", [])
    if gateways is not None and not isinstance(gateways, list):
        raise InvalidProcessDefinitionError("'gateways' must be a list when present.")

    for i, gw in enumerate(gateways or []):
        if not isinstance(gw, dict) or "gateway_pk_id" not in gw:
            raise InvalidProcessDefinitionError(f"gateways[{i}] is missing required field 'gateway_pk_id'.")


def build_graph(data: dict) -> nx.DiGraph:
    """Build a directed graph of tasks and gateways from a process definition.

    Node kinds are ``task``, ``gateway``, ``start``, or ``end``. Edges carry
    ``condition``/``probability`` attributes when they originate from a
    gateway branch. Callers should run ``validate_process_definition``
    first to get a clear error instead of a ``KeyError``.
    """
    g = nx.DiGraph()
    g.graph["process_id"] = data.get("process_id")
    g.graph["process_name"] = data.get("process_name")

    tasks = data["process_task"]
    gateways = data.get("gateways", [])

    for pt in tasks:
        t = pt.get("task", {}) or {}
        task_id = pt["task_id"]
        jts = t.get("jobTasks") or []
        raci = [
            {
                "role": jt.get("role"),
                "pct": jt.get("time_allocation_percentage"),
                "job_name": (jt.get("job") or {}).get("name"),
                "hourly_rate": (jt.get("job") or {}).get("hourlyRate"),
            }
            for jt in jts
        ]
        g.add_node(
            task_id,
            kind="task",
            order=pt.get("order"),
            task_code=t.get("task_code"),
            task_name=t.get("task_name"),
            value_classification=pt.get("value_classification"),
            process_time=t.get("expected_process_time") or 0,
            rework_time=t.get("expected_rework_time") or 0,
            waiting_time=t.get("expected_waiting_time") or 0,
            extra_cost=0.0,
            raci=raci,
        )

    for gw in gateways:
        gid = gw["gateway_pk_id"]
        g.add_node(
            gid,
            kind="gateway",
            gateway_type=gw.get("gateway_type"),
            name=gw.get("name"),
            after_task_id=gw.get("after_task_id"),
            after_gateway_id=gw.get("after_gateway_id"),
        )

    g.add_node("START", kind="start")
    g.add_node("END", kind="end")

    for gw in gateways:
        gid = gw["gateway_pk_id"]
        if gw.get("after_task_id") is not None:
            g.add_edge(gw["after_task_id"], gid)
        elif gw.get("after_gateway_id") is not None:
            g.add_edge(gw["after_gateway_id"], gid)

    for gw in gateways:
        gid = gw["gateway_pk_id"]
        for b in gw.get("branches", []):
            attrs = {"condition": b.get("condition"), "probability": b.get("probability")}
            if b.get("target_task_id") is not None:
                g.add_edge(gid, b["target_task_id"], **attrs)
            elif b.get("target_gateway_id") is not None:
                g.add_edge(gid, b["target_gateway_id"], **attrs)
            elif b.get("connect_to_end"):
                g.add_edge(gid, "END", **attrs)

    tasks_sorted = sorted(tasks, key=lambda pt: pt.get("order") or 0)
    gateway_after_task_ids = {gw["after_task_id"] for gw in gateways if gw.get("after_task_id") is not None}
    task_ids_in_order = [pt["task_id"] for pt in tasks_sorted]

    branch_target_task_ids = set()
    for gw in gateways:
        for b in gw.get("branches", []):
            if b.get("target_task_id") is not None:
                branch_target_task_ids.add(b["target_task_id"])

    for i, tid in enumerate(task_ids_in_order):
        if tid in gateway_after_task_ids:
            continue
        if g.out_degree(tid) > 0:
            continue
        next_tid = task_ids_in_order[i + 1] if i + 1 < len(task_ids_in_order) else None
        if next_tid is not None and next_tid not in branch_target_task_ids:
            g.add_edge(tid, next_tid)
        else:
            g.add_edge(tid, "END")

    for n, kind in list(g.nodes(data="kind")):
        if kind in ("task", "gateway") and g.out_degree(n) == 0:
            g.add_edge(n, "END")

    for n, kind in g.nodes(data="kind"):
        if n in ("START", "END"):
            continue
        if g.in_degree(n) == 0:
            g.add_edge("START", n)

    return g
