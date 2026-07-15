"""Cycle time and cost computation over a process graph."""

from typing import Optional

import networkx as nx

PROBABILISTIC_GATEWAYS = {"EXCLUSIVE", "INCLUSIVE"}
PARALLEL_GATEWAYS = {"PARALLEL", "AND"}


def _task_duration(node_attrs: dict) -> float:
    return (
        (node_attrs.get("process_time") or 0)
        + (node_attrs.get("rework_time") or 0)
        + (node_attrs.get("waiting_time") or 0)
    )


def _task_cost(node_attrs: dict) -> float:
    duration_hours = _task_duration(node_attrs) / 60.0
    total = 0.0
    for entry in node_attrs.get("raci") or []:
        rate = float(entry.get("hourly_rate") or 0)
        pct = float(entry.get("pct") or 0) / 100.0
        total += duration_hours * rate * pct
    total += node_attrs.get("extra_cost") or 0.0
    return total


def compute_metrics(g: nx.DiGraph, start_node: str = "START", _memo: Optional[dict] = None) -> dict:
    """Compute expected cycle time (minutes) and cost for a process graph.

    Gateways are resolved probabilistically (exclusive/inclusive) or by
    taking the longest/summed branch (parallel/AND), walking forward from
    ``start_node`` to ``END``.
    """
    if _memo is None:
        _memo = {}

    def walk(node):
        if node in _memo:
            return _memo[node]
        if node == "END":
            result = (0.0, 0.0)
        else:
            kind = g.nodes[node].get("kind")
            if kind == "task":
                own_time = _task_duration(g.nodes[node])
                own_cost = _task_cost(g.nodes[node])
                successors = list(g.successors(node))
                if not successors:
                    result = (own_time, own_cost)
                else:
                    succ_time, succ_cost = walk(successors[0])
                    result = (own_time + succ_time, own_cost + succ_cost)
            elif kind == "gateway":
                gtype = (g.nodes[node].get("gateway_type") or "").upper()
                edges = list(g.out_edges(node, data=True))
                if not edges:
                    result = (0.0, 0.0)
                elif gtype in PARALLEL_GATEWAYS:
                    branch_results = [walk(v) for (_, v, _) in edges]
                    result = (max(r[0] for r in branch_results),
                              sum(r[1] for r in branch_results))
                else:
                    total_p = sum((a.get("probability") or 0) for (_, _, a) in edges) or 1.0
                    time_acc, cost_acc = 0.0, 0.0
                    for (_, v, a) in edges:
                        p = (a.get("probability") or 0) / total_p
                        vt, vc = walk(v)
                        time_acc += p * vt
                        cost_acc += p * vc
                    result = (time_acc, cost_acc)
            elif kind == "start":
                successors = list(g.successors(node))
                result = walk(successors[0]) if successors else (0.0, 0.0)
            else:
                result = (0.0, 0.0)
        _memo[node] = result
        return result

    time_total, cost_total = walk(start_node)
    return {"cycle_time_minutes": round(time_total, 2), "cost": round(cost_total, 2)}
