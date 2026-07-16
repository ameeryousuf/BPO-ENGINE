"""Parsing and validation of BPMN process JSON into a directed graph.

The graph representation is the common substrate consumed by every other
core module (metrics, heuristics, the RL environment, and replay).
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import networkx as nx

from app.core import fx
from app.exceptions import InvalidProcessDefinitionError

logger = logging.getLogger(__name__)

MAX_TASKS = 200
PROBABILITY_TOLERANCE = 0.01
NEGATIVE_TIME_FIELDS = ("expected_process_time", "expected_rework_time", "expected_waiting_time")


def load_process(json_path: "str | Path") -> dict:
    """Load a process definition from a JSON file on disk.

    Intended for CLI/test use against fixture files; the API operates on
    already-parsed dicts and does not touch the filesystem.
    """
    with open(json_path, "r") as f:
        return json.load(f)


def _coerce_float(value: Any, error_message: str) -> float:
    """Cast ``value`` to float, raising a clear, named error on failure.

    Handles the common case of numeric fields (percentages, rates,
    probabilities, durations) arriving as strings from upstream systems.
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidProcessDefinitionError(error_message) from exc


def validate_process_definition(data: Any) -> None:
    """Validate ``data`` and coerce its numeric fields in place.

    Checks the minimal shape required to build a graph, that every
    gateway reference resolves to a real task/gateway, that gateway
    branch probabilities sum to ~1.0, that task IDs are unique, that
    time fields are non-negative, and that numeric fields which commonly
    arrive as strings (``time_allocation_percentage``, ``hourlyRate``,
    branch ``probability``) are valid numbers. Values that pass the
    numeric checks are coerced to ``float`` in place so downstream code
    never has to re-parse them.

    Raises ``InvalidProcessDefinitionError`` with a human-readable message
    naming the offending field/task/gateway, describing the first problem
    found.
    """
    if not isinstance(data, dict):
        raise InvalidProcessDefinitionError("Process definition must be a JSON object.")

    tasks = data.get("process_task")
    if not isinstance(tasks, list) or len(tasks) == 0:
        raise InvalidProcessDefinitionError("Process definition must contain a non-empty 'process_task' list.")

    if len(tasks) > MAX_TASKS:
        raise InvalidProcessDefinitionError(
            f"Process definition has {len(tasks)} tasks, which exceeds the maximum of {MAX_TASKS}."
        )

    task_ids: set = set()
    for i, pt in enumerate(tasks):
        if not isinstance(pt, dict):
            raise InvalidProcessDefinitionError(f"process_task[{i}] must be an object.")
        if "task_id" not in pt:
            raise InvalidProcessDefinitionError(f"process_task[{i}] is missing required field 'task_id'.")
        task_id = pt["task_id"]
        if task_id in task_ids:
            raise InvalidProcessDefinitionError(f"Duplicate task_id {task_id!r} found in process_task.")
        task_ids.add(task_id)
        if not isinstance(pt.get("task"), dict):
            raise InvalidProcessDefinitionError(f"process_task[{i}] is missing required object field 'task'.")

        task = pt["task"]
        for field in NEGATIVE_TIME_FIELDS:
            if field not in task or task[field] is None:
                continue
            value = _coerce_float(
                task[field],
                f"Invalid numeric value for field '{field}' on task {task_id}: {task[field]!r}.",
            )
            if value < 0:
                raise InvalidProcessDefinitionError(
                    f"Task {task_id} field '{field}' must not be negative (got {value})."
                )
            task[field] = value

        for jt in task.get("jobTasks") or []:
            if "time_allocation_percentage" in jt and jt["time_allocation_percentage"] is not None:
                raw = jt["time_allocation_percentage"]
                jt["time_allocation_percentage"] = _coerce_float(
                    raw,
                    f"Invalid numeric value for field 'time_allocation_percentage' on task {task_id}: {raw!r}.",
                )
            job = jt.get("job")
            if isinstance(job, dict) and "hourlyRate" in job and job["hourlyRate"] is not None:
                raw = job["hourlyRate"]
                job["hourlyRate"] = _coerce_float(
                    raw, f"Invalid numeric value for field 'hourlyRate' on task {task_id}: {raw!r}."
                )

    gateways = data.get("gateways", [])
    if gateways is not None and not isinstance(gateways, list):
        raise InvalidProcessDefinitionError("'gateways' must be a list when present.")
    gateways = gateways or []

    gateway_ids: set = {gw["gateway_pk_id"] for gw in gateways if isinstance(gw, dict) and "gateway_pk_id" in gw}

    for i, gw in enumerate(gateways):
        if not isinstance(gw, dict) or "gateway_pk_id" not in gw:
            raise InvalidProcessDefinitionError(f"gateways[{i}] is missing required field 'gateway_pk_id'.")
        gw_id = gw["gateway_pk_id"]

        after_task_id = gw.get("after_task_id")
        if after_task_id is not None and after_task_id not in task_ids:
            raise InvalidProcessDefinitionError(
                f"Gateway {gw_id} has after_task_id {after_task_id!r} which does not exist in process_task."
            )
        after_gateway_id = gw.get("after_gateway_id")
        if after_gateway_id is not None and after_gateway_id not in gateway_ids:
            raise InvalidProcessDefinitionError(
                f"Gateway {gw_id} has after_gateway_id {after_gateway_id!r} which does not exist in gateways."
            )

        prob_total = 0.0
        for j, b in enumerate(gw.get("branches") or []):
            target_task_id = b.get("target_task_id")
            if target_task_id is not None and target_task_id not in task_ids:
                raise InvalidProcessDefinitionError(
                    f"Gateway {gw_id} branch[{j}] has target_task_id {target_task_id!r} "
                    "which does not exist in process_task."
                )
            target_gateway_id = b.get("target_gateway_id")
            if target_gateway_id is not None and target_gateway_id not in gateway_ids:
                raise InvalidProcessDefinitionError(
                    f"Gateway {gw_id} branch[{j}] has target_gateway_id {target_gateway_id!r} "
                    "which does not exist in gateways."
                )
            if "probability" in b and b["probability"] is not None:
                raw = b["probability"]
                b["probability"] = _coerce_float(
                    raw, f"Invalid numeric value for field 'probability' on gateway {gw_id} branch[{j}]: {raw!r}."
                )
            prob_total += b.get("probability") or 0.0

        if gw.get("branches") and abs(prob_total - 1.0) > PROBABILITY_TOLERANCE:
            raise InvalidProcessDefinitionError(
                f"Gateway {gw_id} branch probabilities sum to {prob_total:.4f}, expected ~1.0 "
                f"(tolerance ±{PROBABILITY_TOLERANCE})."
            )


def validate_graph_reachability(g: "nx.DiGraph") -> None:
    """Ensure every task/gateway node can be reached from START and can reach END.

    Run after ``build_graph``: an orphaned node is otherwise silently
    ignored by cost/time computation and could strand the RL agent, so we
    fail fast with a message naming the unreachable node instead.
    """
    reachable_from_start = nx.descendants(g, "START") | {"START"}
    can_reach_end = nx.ancestors(g, "END") | {"END"}

    for n, kind in g.nodes(data="kind"):
        if kind not in ("task", "gateway"):
            continue
        if n not in reachable_from_start:
            raise InvalidProcessDefinitionError(f"{kind} {n!r} is unreachable from START.")
        if n not in can_reach_end:
            raise InvalidProcessDefinitionError(f"{kind} {n!r} cannot reach END.")


def _build_raci_entry(jt: dict, task_id) -> dict:
    """Build one RACI entry, converting its job's hourly rate to PKR.

    Every downstream consumer (metrics, heuristics) sums ``hourly_rate``
    across RACI entries as if it were already one common currency, so the
    conversion happens here, once, at parse time - nothing past this point
    needs to know currencies exist.

    ``raw_rate``/``currency`` (the unconverted hourly rate and its original
    currency code) and the job's capacity fields (``job_id``,
    ``hours_per_day``, ``days_per_week``, ``capacity_buffer``) are carried
    alongside the normalized ``hourly_rate`` so that later analysis (see
    ``app.core.quantitative_analysis``) can reconstruct both the legacy
    mixed-currency total and per-resource capacity without re-reading the
    original JSON.
    """
    job = jt.get("job") or {}
    raw_rate = job.get("hourlyRate")
    currency = job.get("currencyType") or "PKR"
    hourly_rate = raw_rate
    if raw_rate is not None:
        try:
            hourly_rate = fx.convert_to_pkr(float(raw_rate), currency)
        except ValueError as exc:
            raise InvalidProcessDefinitionError(
                f"Task {task_id} job {job.get('name')!r}: {exc}"
            ) from exc
    return {
        "role": jt.get("role"),
        "pct": jt.get("time_allocation_percentage"),
        "job_name": job.get("name"),
        "hourly_rate": hourly_rate,
        "raw_rate": raw_rate,
        "currency": currency,
        "job_id": job.get("job_id"),
        "hours_per_day": job.get("hours_per_day"),
        "days_per_week": job.get("days_per_week"),
        "capacity_buffer": job.get("capacity_buffer"),
    }


def build_graph(data: dict) -> nx.DiGraph:
    """Build a directed graph of tasks and gateways from a process definition.

    Node kinds are ``task``, ``gateway``, ``start``, or ``end``. Edges carry
    ``condition``/``probability`` attributes when they originate from a
    gateway branch. Callers should run ``validate_process_definition``
    first to get a clear error instead of a ``KeyError``.

    Each RACI entry's ``hourly_rate`` is converted to PKR here (see
    ``_build_raci_entry``) based on its job's ``currencyType``, so this is
    the one point per request where live FX rates are fetched (and
    cached) - not something that happens per training episode.
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
        raci = [_build_raci_entry(jt, task_id) for jt in jts]
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
            extra_cost_raw=0.0,
            frequency_interval=t.get("frequency_interval"),
            frequency_period=t.get("frequency_period"),
            occurrences=t.get("occurrences"),
            raci=raci,
        )

    for gw in gateways:
        gid = gw["gateway_pk_id"]
        branches = []
        for b in gw.get("branches", []):
            if b.get("target_task_id") is not None:
                target = b["target_task_id"]
            elif b.get("target_gateway_id") is not None:
                target = b["target_gateway_id"]
            else:
                target = "END"
            branches.append({
                "target": target,
                "condition": b.get("condition"),
                "probability": b.get("probability"),
            })
        g.add_node(
            gid,
            kind="gateway",
            gateway_type=gw.get("gateway_type"),
            name=gw.get("name"),
            after_task_id=gw.get("after_task_id"),
            after_gateway_id=gw.get("after_gateway_id"),
            branches=branches,
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
