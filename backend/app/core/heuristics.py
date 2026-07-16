"""Business process redesign heuristics.

Each heuristic exposes a ``*_candidates`` generator that yields applicable
targets for a given graph, and a ``*_apply`` function that returns a new
graph with the heuristic applied. ``HEURISTICS`` is the registry consumed
by the RL environment and trainer; ``all_candidates`` enumerates every
applicable (heuristic_id, target) pair for a graph.
"""

import copy
from collections import Counter, defaultdict
from typing import Iterator, Tuple

import networkx as nx

AUTOMATION_TIME_CUT = 0.6
COMPOSITION_MAX_COMBINED = 1200
EXTRA_RESOURCE_TIME_CUT = 0.3
EXTRA_RESOURCE_COST_SURCHARGE = 0.2
INTERFACE_REWORK_CUT = 0.5
OUTSOURCE_RATE_CUT = 0.25


def _task_nodes(g: nx.DiGraph) -> list:
    return [n for n, k in g.nodes(data="kind") if k == "task"]


def _duration(g: nx.DiGraph, n) -> float:
    a = g.nodes[n]
    return (a.get("process_time") or 0) + (a.get("rework_time") or 0) + (a.get("waiting_time") or 0)


def _sole_role(g: nx.DiGraph, n, role_letter: str):
    raci = g.nodes[n].get("raci") or []
    matches = [r for r in raci if r.get("role") == role_letter]
    return matches[0] if len(matches) == 1 else None


def _reroute_gateway_branches(g: nx.DiGraph, node, old_target, new_target) -> None:
    """Update a gateway's explicit branch list when a heuristic changes what
    ``node``'s edge to ``old_target`` points to.

    ``node`` may have several branches sharing ``old_target`` (e.g. two
    conditions both leading to END); every one of them is rerouted so that
    a sibling branch unrelated to the change is never dropped. No-op for
    non-gateway nodes or gateways with no explicit branch list (e.g. the
    synthetic AND/PARALLEL split-join gateways created by ``parallelism_apply``).
    """
    if g.nodes[node].get("kind") != "gateway":
        return
    branches = g.nodes[node].get("branches")
    if not branches:
        return
    for b in branches:
        if b.get("target") == old_target:
            b["target"] = new_target


def _task_hourly_cost(g: nx.DiGraph, n) -> float:
    dur_h = _duration(g, n) / 60.0
    total = 0.0
    for r in g.nodes[n].get("raci") or []:
        total += dur_h * float(r.get("hourly_rate") or 0) * (float(r.get("pct") or 0) / 100.0)
    return total


def _task_hourly_cost_raw(g: nx.DiGraph, n) -> float:
    """Same as ``_task_hourly_cost`` but using each RACI entry's unconverted
    ``raw_rate`` instead of the PKR-normalized ``hourly_rate``.

    Kept in lockstep with ``_task_hourly_cost`` so that a redesigned graph's
    raw (mixed-currency, uncorrected) cost total stays reconstructible
    end-to-end - see ``extra_resources_apply``, the only heuristic that adds
    a currency-denominated surcharge.
    """
    dur_h = _duration(g, n) / 60.0
    total = 0.0
    for r in g.nodes[n].get("raci") or []:
        total += dur_h * float(r.get("raw_rate") or 0) * (float(r.get("pct") or 0) / 100.0)
    return total


def automation_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    tasks = _task_nodes(g)
    if not tasks:
        return
    avg_duration = sum(_duration(g, n) for n in tasks) / len(tasks)
    for n in tasks:
        if g.nodes[n].get("automated"):
            continue
        r = _sole_role(g, n, "R")
        if r is None:
            continue
        if _duration(g, n) < avg_duration:
            yield (n,)


def automation_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    (n,) = target
    g2 = copy.deepcopy(g)
    g2.nodes[n]["process_time"] = round(g2.nodes[n]["process_time"] * (1 - AUTOMATION_TIME_CUT), 2)
    g2.nodes[n]["automated"] = True
    return g2


def elimination_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    for n in _task_nodes(g):
        if g.nodes[n].get("value_classification") == "NVA":
            if g.in_degree(n) == 1 and g.out_degree(n) == 1:
                yield (n,)


def elimination_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    (n,) = target
    g2 = copy.deepcopy(g)
    pred = list(g2.predecessors(n))[0]
    succ = list(g2.successors(n))[0]
    edge_attrs = g2.get_edge_data(pred, n) or {}
    _reroute_gateway_branches(g2, pred, n, succ)
    g2.remove_node(n)
    g2.add_edge(pred, succ, **edge_attrs)
    return g2


def composition_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    for n in _task_nodes(g):
        succs = list(g.successors(n))
        if len(succs) != 1:
            continue
        m = succs[0]
        if g.nodes[m].get("kind") != "task" or g.in_degree(m) != 1:
            continue
        r1, r2 = _sole_role(g, n, "R"), _sole_role(g, m, "R")
        if r1 and r2 and r1.get("job_name") == r2.get("job_name"):
            if _duration(g, n) + _duration(g, m) <= COMPOSITION_MAX_COMBINED:
                yield (n, m)


def composition_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    n, m = target
    g2 = copy.deepcopy(g)
    for key in ("process_time", "rework_time", "waiting_time"):
        g2.nodes[n][key] = (g2.nodes[n].get(key) or 0) + (g2.nodes[m].get(key) or 0)
    g2.nodes[n]["task_name"] = f"{g2.nodes[n]['task_name']} + {g2.nodes[m]['task_name']}"
    succ = list(g2.successors(m))
    g2.remove_node(m)
    if succ:
        g2.add_edge(n, succ[0])
    return g2


def parallelism_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    for n in _task_nodes(g):
        succs = list(g.successors(n))
        if len(succs) != 1:
            continue
        m = succs[0]
        if g.nodes[m].get("kind") != "task" or g.in_degree(m) != 1:
            continue
        r1, r2 = _sole_role(g, n, "R"), _sole_role(g, m, "R")
        if r1 and r2 and r1.get("job_name") != r2.get("job_name"):
            if g.in_degree(n) == 1 and g.out_degree(m) == 1:
                yield (n, m)


def parallelism_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    n, m = target
    g2 = copy.deepcopy(g)
    pred = list(g2.predecessors(n))[0]
    succ = list(g2.successors(m))[0]
    pred_edge_attrs = g2.get_edge_data(pred, n) or {}
    split_id, join_id = f"AND_SPLIT_{n}_{m}", f"AND_JOIN_{n}_{m}"
    g2.add_node(split_id, kind="gateway", gateway_type="PARALLEL", name=f"Split before {n}/{m}")
    g2.add_node(join_id, kind="gateway", gateway_type="PARALLEL", name=f"Join after {n}/{m}")
    _reroute_gateway_branches(g2, pred, n, split_id)
    g2.remove_edge(pred, n)
    g2.remove_edge(n, m)
    g2.remove_edge(m, succ)
    g2.add_edge(pred, split_id, **pred_edge_attrs)
    g2.add_edge(split_id, n)
    g2.add_edge(split_id, m)
    g2.add_edge(n, join_id)
    g2.add_edge(m, join_id)
    g2.add_edge(join_id, succ)
    return g2


def resequencing_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    for n in _task_nodes(g):
        succs = list(g.successors(n))
        if len(succs) != 1:
            continue
        m = succs[0]
        if g.nodes[m].get("kind") != "task" or g.in_degree(m) != 1 or g.in_degree(n) != 1:
            continue
        if _duration(g, m) < _duration(g, n):
            yield (n, m)


def resequencing_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    n, m = target
    g2 = copy.deepcopy(g)
    pred = list(g2.predecessors(n))[0]
    succ = list(g2.successors(m))[0]
    pred_edge_attrs = g2.get_edge_data(pred, n) or {}
    succ_edge_attrs = g2.get_edge_data(m, succ) or {}
    _reroute_gateway_branches(g2, pred, n, m)
    g2.remove_edge(pred, n)
    g2.remove_edge(n, m)
    g2.remove_edge(m, succ)
    g2.add_edge(pred, m, **pred_edge_attrs)
    g2.add_edge(m, n)
    g2.add_edge(n, succ, **succ_edge_attrs)
    return g2


def extra_resources_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    tasks = _task_nodes(g)
    if not tasks:
        return
    bottleneck = max(tasks, key=lambda n: _duration(g, n))
    if not g.nodes[bottleneck].get("extra_resourced"):
        yield (bottleneck,)


def extra_resources_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    (n,) = target
    g2 = copy.deepcopy(g)
    cost_before = _task_hourly_cost(g2, n)
    cost_before_raw = _task_hourly_cost_raw(g2, n)
    g2.nodes[n]["process_time"] = round(g2.nodes[n]["process_time"] * (1 - EXTRA_RESOURCE_TIME_CUT), 2)
    g2.nodes[n]["extra_cost"] = (g2.nodes[n].get("extra_cost") or 0) + cost_before * EXTRA_RESOURCE_COST_SURCHARGE
    g2.nodes[n]["extra_cost_raw"] = (
        (g2.nodes[n].get("extra_cost_raw") or 0) + cost_before_raw * EXTRA_RESOURCE_COST_SURCHARGE
    )
    g2.nodes[n]["extra_resourced"] = True
    return g2


def centralization_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    groups = defaultdict(list)
    for n in _task_nodes(g):
        r = _sole_role(g, n, "R")
        if r:
            key = (r.get("job_name") or "")[:3]
            groups[key].append((n, r.get("job_name")))
    for key, members in groups.items():
        distinct_jobs = {j for _, j in members}
        if len(members) >= 2 and len(distinct_jobs) >= 2:
            yield tuple(n for n, _ in members)


def centralization_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    g2 = copy.deepcopy(g)
    jobs = [(_sole_role(g2, n, "R") or {}).get("job_name") for n in target]
    winner = Counter(jobs).most_common(1)[0][0]
    winner_entry = None
    for n in target:
        r = _sole_role(g2, n, "R")
        if r and r.get("job_name") == winner:
            winner_entry = r
            break
    for n in target:
        for r in g2.nodes[n]["raci"]:
            if r.get("role") == "R":
                r["job_name"] = winner
                if winner_entry:
                    r["hourly_rate"] = winner_entry.get("hourly_rate")
    return g2


def _checkpoint_segments(g: nx.DiGraph) -> list:
    segments = []
    for n, k in g.nodes(data="kind"):
        if k != "gateway":
            continue
        has_end_branch = any(v == "END" for _, v in g.out_edges(n))
        if not has_end_branch:
            continue
        preds = list(g.predecessors(n))
        if len(preds) == 1 and g.nodes[preds[0]].get("kind") == "task":
            segments.append((preds[0], n))
    return segments


def knockout_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    segments = _checkpoint_segments(g)
    for i in range(len(segments) - 1):
        t1, gw1 = segments[i]
        t2, gw2 = segments[i + 1]
        continue_target_1 = next((v for _, v, a in g.out_edges(gw1, data=True) if v != "END"), None)
        continue_target_2 = next((v for _, v, a in g.out_edges(gw2, data=True) if v != "END"), None)
        if continue_target_1 == t2 and continue_target_2 is not None:
            yield (t1, gw1, t2, gw2)


def knockout_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    t1, gw1, t2, gw2 = target
    g2 = copy.deepcopy(g)
    pred = list(g2.predecessors(t1))[0]
    succ = next(v for _, v, a in g2.out_edges(gw2, data=True) if v != "END")
    pred_edge_attrs = g2.get_edge_data(pred, t1) or {}
    gw2_continue_attrs = g2.get_edge_data(gw2, succ) or {}
    gw1_continue_attrs = g2.get_edge_data(gw1, t2) or {}
    _reroute_gateway_branches(g2, pred, t1, t2)
    _reroute_gateway_branches(g2, gw2, succ, t1)
    _reroute_gateway_branches(g2, gw1, t2, succ)
    g2.remove_edge(pred, t1)
    g2.remove_edge(gw2, succ)
    g2.remove_edge(gw1, t2)
    g2.add_edge(pred, t2, **pred_edge_attrs)
    g2.add_edge(gw2, t1, **gw2_continue_attrs)
    g2.add_edge(gw1, succ, **gw1_continue_attrs)
    return g2


def interfacing_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    for n in _task_nodes(g):
        preds = [p for p in g.predecessors(n) if g.nodes[p].get("kind") == "task"]
        if not preds:
            continue
        r_here = _sole_role(g, n, "R")
        r_pred = _sole_role(g, preds[0], "R")
        if r_here and r_pred and r_here.get("job_name") != r_pred.get("job_name"):
            if (g.nodes[n].get("rework_time") or 0) > 0:
                yield (n,)


def interfacing_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    (n,) = target
    g2 = copy.deepcopy(g)
    g2.nodes[n]["rework_time"] = round(g2.nodes[n]["rework_time"] * (1 - INTERFACE_REWORK_CUT), 2)
    return g2


def outsourcing_candidates(g: nx.DiGraph) -> Iterator[tuple]:
    costs = {n: _task_hourly_cost(g, n) for n in _task_nodes(g)}
    if not costs:
        return
    avg = sum(costs.values()) / len(costs)
    for n, c in costs.items():
        if c > avg and not g.nodes[n].get("outsourced"):
            yield (n,)


def outsourcing_apply(g: nx.DiGraph, target: tuple) -> nx.DiGraph:
    (n,) = target
    g2 = copy.deepcopy(g)
    for r in g2.nodes[n].get("raci") or []:
        if r.get("role") == "R":
            r["hourly_rate"] = round(float(r.get("hourly_rate") or 0) * (1 - OUTSOURCE_RATE_CUT), 2)
            # Keep raw_rate (the unconverted, mixed-currency figure - see
            # app.core.quantitative_analysis) in lockstep with hourly_rate,
            # the same way extra_resources_apply tracks extra_cost_raw:
            # otherwise the raw cost total silently stops matching what
            # actually happened to this RACI entry's rate.
            if r.get("raw_rate") is not None:
                r["raw_rate"] = round(float(r.get("raw_rate") or 0) * (1 - OUTSOURCE_RATE_CUT), 2)
    g2.nodes[n]["outsourced"] = True
    return g2


HEURISTICS = {
    "activity_automation":  (automation_candidates, automation_apply),
    "activity_elimination": (elimination_candidates, elimination_apply),
    "activity_composition": (composition_candidates, composition_apply),
    "parallelism":          (parallelism_candidates, parallelism_apply),
    "resequencing":         (resequencing_candidates, resequencing_apply),
    "extra_resources":      (extra_resources_candidates, extra_resources_apply),
    "centralization":       (centralization_candidates, centralization_apply),
    "knockout":             (knockout_candidates, knockout_apply),
    "interfacing":          (interfacing_candidates, interfacing_apply),
    "outsourcing":          (outsourcing_candidates, outsourcing_apply),
}


def all_candidates(g: nx.DiGraph) -> list:
    """Enumerate every applicable (heuristic_id, target) pair for a graph."""
    out = []
    for hid, (cand_fn, _) in HEURISTICS.items():
        for target in cand_fn(g):
            out.append((hid, target))
    return out
