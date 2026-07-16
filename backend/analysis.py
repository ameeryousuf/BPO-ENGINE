from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bpmn_graph import GATEWAY_TAGS, TASK_TAGS, detect_back_edges, elem_name, parse_bpmn_graph
from currency import to_pkr


class Metric(str, Enum):
    CYCLE_TIME = "cycle_time"
    THEORETICAL = "theoretical"
    RESOURCE_COST = "resource_cost"
    RACI_COST = "raci_cost"


@dataclass
class AnalysisResult:
    cycle_time: float
    theoretical_cycle_time: float
    cycle_time_efficiency: float
    resource_cost: float
    raci_cost: float
    time_unit: str = "minutes"
    cost_unit: str = "PKR"


def analyze_process(process_data: dict) -> AnalysisResult:
    graph = parse_bpmn_graph(process_data["bpmn_xml"])

    if len(graph.start_events) != 1:
        raise ValueError("process must have exactly one start event for flow analysis")

    tasks_by_activity = _build_task_index(process_data)
    gateway_by_name = {gw["name"]: gw for gw in process_data.get("gateways", [])}
    start = graph.start_events[0]

    cycle_time = _compute(start, graph, tasks_by_activity, gateway_by_name, Metric.CYCLE_TIME)
    theoretical_cycle_time = _compute(start, graph, tasks_by_activity, gateway_by_name, Metric.THEORETICAL)
    resource_cost = _compute(start, graph, tasks_by_activity, gateway_by_name, Metric.RESOURCE_COST)
    raci_cost = _compute(start, graph, tasks_by_activity, gateway_by_name, Metric.RACI_COST)

    cycle_time_efficiency = (
        theoretical_cycle_time / cycle_time if cycle_time > 0 else 0.0
    )

    return AnalysisResult(
        cycle_time=round(cycle_time, 2),
        theoretical_cycle_time=round(theoretical_cycle_time, 2),
        cycle_time_efficiency=round(cycle_time_efficiency, 4),
        resource_cost=round(resource_cost, 2),
        raci_cost=round(raci_cost, 2),
    )


def _build_task_index(process_data: dict) -> dict:
    index = {}
    for pt in process_data.get("process_task", []):
        task = pt.get("task")
        if task is None:
            continue
        index[f"Activity_{pt['task_id']}"] = task
    return index


def _work_minutes(task: dict) -> float:
    processing = float(task.get("expected_process_time") or 0)
    rework = float(task.get("expected_rework_time") or 0)
    return processing + rework


def _job_hourly_rate_pkr(job: dict) -> float:
    rate = float(job.get("hourlyRate") or 0)
    currency = job.get("currencyType", "PKR")
    return to_pkr(rate, currency)


def _resource_cost(task: dict) -> float:
    job_tasks = task.get("jobTasks") or []
    responsible = next((jt for jt in job_tasks if jt.get("role") == "R"), None)
    if responsible is None:
        return 0.0
    hourly_rate_pkr = _job_hourly_rate_pkr(responsible.get("job", {}))
    hours = _work_minutes(task) / 60.0
    return hourly_rate_pkr * hours


def _raci_cost(task: dict) -> float:
    job_tasks = task.get("jobTasks") or []
    if not job_tasks:
        return 0.0

    total_pct = sum(float(jt.get("time_allocation_percentage") or 0) for jt in job_tasks)
    if total_pct <= 0:
        return 0.0

    hours = _work_minutes(task) / 60.0
    total_cost = 0.0
    for jt in job_tasks:
        hourly_rate_pkr = _job_hourly_rate_pkr(jt.get("job", {}))
        pct = float(jt.get("time_allocation_percentage") or 0)
        share = pct / total_pct
        total_cost += hourly_rate_pkr * hours * share

    return total_cost


def _task_value(task: dict, metric: Metric) -> float:
    if metric == Metric.RESOURCE_COST:
        return _resource_cost(task)
    if metric == Metric.RACI_COST:
        return _raci_cost(task)
    work = _work_minutes(task)
    if metric == Metric.THEORETICAL:
        return work
    waiting = float(task.get("expected_waiting_time") or 0)
    return work + waiting


def _find_probability(gateway: dict, flow, graph) -> float:
    name = flow.get("name")
    target = flow.get("targetRef")
    branches = gateway.get("branches", [])

    for branch in branches:
        if name is not None and branch.get("condition") == name:
            return float(branch.get("probability") or 0)

    for branch in branches:
        if branch.get("target_task_id") is not None and target == f"Activity_{branch['target_task_id']}":
            return float(branch.get("probability") or 0)

    for branch in branches:
        end_name = branch.get("end_event_name")
        if end_name and target in graph.nodes and elem_name(graph.nodes[target]) == end_name:
            return float(branch.get("probability") or 0)

    raise ValueError(
        f"no matching branch/probability found for flow to '{target}' "
        f"at gateway '{gateway.get('name')}'"
    )


def _resolve_loops(graph, tasks_by_activity, gateway_by_name, metric, memo):
    back_edges = detect_back_edges(graph)

    for gateway_node, header, back_flow in back_edges:
        name = elem_name(graph.nodes[gateway_node])
        gateway = gateway_by_name.get(name)
        if gateway is None:
            raise ValueError(f"loop gateway '{name}' has no matching entry in gateways[]")

        r = _find_probability(gateway, back_flow, graph)

        exit_flows = [f for f in graph.outgoing[gateway_node] if f is not back_flow]
        if len(exit_flows) != 1:
            raise ValueError(f"loop gateway '{name}' must have exactly one non-looping exit flow")
        exit_flow = exit_flows[0]

        header_successors = graph.successors(header)
        if len(header_successors) != 1:
            raise ValueError(f"loop header '{header}' must have exactly one outgoing flow")

        body_value = _compute(
            header_successors[0], graph, tasks_by_activity, gateway_by_name, metric,
            stop=gateway_node,
        )

        exit_value = _compute(
            exit_flow.get("targetRef"), graph, tasks_by_activity, gateway_by_name, metric,
            memo=memo,
        )

        memo[header] = body_value / (1 - r) + exit_value


def _compute(start_node, graph, tasks_by_activity, gateway_by_name, metric, stop=None, memo=None):
    if memo is None:
        memo = {}
        _resolve_loops(graph, tasks_by_activity, gateway_by_name, metric, memo)
    return _path_value(start_node, graph, tasks_by_activity, gateway_by_name, metric, memo, stop)


def _path_value(node_id, graph, tasks_by_activity, gateway_by_name, metric, memo, stop):
    if node_id == stop:
        return 0.0
    if node_id in memo:
        return memo[node_id]
    if graph.is_end(node_id):
        return 0.0

    tag = graph.tag_of(node_id)

    if tag in TASK_TAGS:
        task = tasks_by_activity.get(node_id)
        if task is None:
            raise ValueError(f"no task data found for activity '{node_id}'")
        successors = graph.successors(node_id)
        if len(successors) != 1:
            raise ValueError(f"task '{node_id}' must have exactly one outgoing flow")
        value = _task_value(task, metric) + _path_value(
            successors[0], graph, tasks_by_activity, gateway_by_name, metric, memo, stop
        )
        memo[node_id] = value
        return value

    if tag in GATEWAY_TAGS:
        successors = graph.successors(node_id)
        if len(successors) <= 1:
            value = (
                _path_value(successors[0], graph, tasks_by_activity, gateway_by_name, metric, memo, stop)
                if successors else 0.0
            )
            memo[node_id] = value
            return value

        name = elem_name(graph.nodes[node_id])
        gateway = gateway_by_name.get(name)
        if gateway is None:
            raise ValueError(f"gateway '{name}' has multiple outgoing flows but no matching entry in gateways[]")

        branch_values = []
        for flow in graph.outgoing[node_id]:
            target = flow.get("targetRef")
            probability = _find_probability(gateway, flow, graph)
            value = _path_value(target, graph, tasks_by_activity, gateway_by_name, metric, memo, stop)
            branch_values.append((probability, value))

        if gateway.get("gateway_type") == "PARALLEL":
            if metric in (Metric.CYCLE_TIME, Metric.THEORETICAL):
                result = max(v for _, v in branch_values)
            else:
                result = sum(v for _, v in branch_values)
        else:
            total_probability = sum(p for p, _ in branch_values)
            if abs(total_probability - 1.0) > 0.001:
                raise ValueError(f"gateway '{name}' branch probabilities sum to {total_probability}, expected 1.0")
            result = sum(p * v for p, v in branch_values)

        memo[node_id] = result
        return result

    successors = graph.successors(node_id)
    value = (
        _path_value(successors[0], graph, tasks_by_activity, gateway_by_name, metric, memo, stop)
        if successors else 0.0
    )
    memo[node_id] = value
    return value