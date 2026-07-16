"""Quantitative Process Analysis (Dumas et al., *Fundamentals of Business
Process Management*, 2nd ed., Chapter 7) over the graph representation
produced by ``app.core.parser.build_graph``.

This module is generic over the schema: every function walks the actual
``gateways``/``branches`` graph rather than assuming a fixed shape, so it
applies to any process definition the parser can build a graph for, not
just the sample academic-approval process used to validate it.

Chapter 7 techniques implemented, one function per technique:

- ``flow_analysis``      - Flow Analysis / the Cycle Time Law: Sequential,
                            Parallel (AND-split/join), Conditional
                            (XOR/inclusive-split), and Repetition (rework
                            loop) patterns, applied by walking the graph
                            and classifying each construct.
- ``cycle_time_efficiency`` - CTE = value-adding time / total cycle time.
- ``cost_analysis``      - Activity-Based Costing, rolled up through the
                            same probability-weighted graph, in both raw
                            (mixed-currency, uncorrected) and
                            currency-normalized bases.
- ``resource_utilization`` - Per-resource required vs. available capacity
                            (utilization ratio) and Little's Law
                            (WIP = arrival rate x cycle time).
- ``compare``            - Runs the existing RL redesign pipeline
                            (parse -> train -> replay) to obtain the to-be
                            graph, then runs all of the above on both the
                            as-is and to-be graphs and assembles the
                            before/after report.
"""

from dataclasses import dataclass
from itertools import count
from typing import Optional

import networkx as nx

from app.core.heuristics import HEURISTICS, all_candidates
from app.core.metrics import PARALLEL_GATEWAYS
from app.core.parser import build_graph, load_process, validate_graph_reachability, validate_process_definition
from app.core.replay import replay_sequence, serialize_graph
from app.core.trainer import train

MINUTES_PER_HOUR = 60.0
MINUTES_PER_WEEK = 7 * 24 * 60

# frequency_period values are converted to an equivalent number of weeks
# per occurrence so every task's instance rate can be compared on one
# timescale (weeks), matching the weekly units job capacity is expressed in
# (hours_per_day x days_per_week).
_PERIOD_TO_WEEKS = {
    "DAY": 1 / 7,
    "WEEK": 1.0,
    "MONTH": 52.0 / 12.0,
    "QUARTER": 13.0,
    "YEAR": 52.0,
}


# ---------------------------------------------------------------------------
# Flow value: the four accumulators every pattern combines.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlowValue:
    """Expected minutes/cost contributed by a subgraph, from some node to END."""

    time: float = 0.0
    va_time: float = 0.0
    cost_raw: float = 0.0
    cost_norm: float = 0.0

    def as_tuple(self) -> tuple:
        return (self.time, self.va_time, self.cost_raw, self.cost_norm)


_ZERO = FlowValue()


def _seq(a: FlowValue, b: FlowValue) -> FlowValue:
    """Sequential pattern: CT = CT(A) + CT(B)."""
    return FlowValue(a.time + b.time, a.va_time + b.va_time, a.cost_raw + b.cost_raw, a.cost_norm + b.cost_norm)


def _conditional(weighted_branches: list) -> FlowValue:
    """Conditional (XOR/inclusive-split) pattern: CT = sum(p_i * CT(branch_i))."""
    total_p = sum(p for p, _ in weighted_branches) or 1.0
    time = va = cr = cn = 0.0
    for p, fv in weighted_branches:
        w = p / total_p
        time += w * fv.time
        va += w * fv.va_time
        cr += w * fv.cost_raw
        cn += w * fv.cost_norm
    return FlowValue(time, va, cr, cn)


def _parallel(branch_values: list) -> FlowValue:
    """Parallel (AND-split/join) pattern: CT = max(branches); cost/VA-time
    accumulate across every branch since all of them actually execute."""
    if not branch_values:
        return _ZERO
    return FlowValue(
        max(fv.time for fv in branch_values),
        sum(fv.va_time for fv in branch_values),
        sum(fv.cost_raw for fv in branch_values),
        sum(fv.cost_norm for fv in branch_values),
    )


def _repetition(body: FlowValue, loop_probability: float) -> FlowValue:
    """Repetition/loop pattern: CT = CT(single_pass) * 1/(1 - p)."""
    if loop_probability >= 1.0:
        raise ValueError(
            f"Loop probability {loop_probability} implies the loop never exits "
            "(1/(1-p) is undefined) - this process definition has no way out of a rework cycle."
        )
    factor = 1.0 / (1.0 - loop_probability)
    return FlowValue(body.time * factor, body.va_time * factor, body.cost_raw * factor, body.cost_norm * factor)


def _task_flow_value(attrs: dict) -> FlowValue:
    """A task's own contribution: its duration/cost, not anything downstream.

    Mirrors ``app.core.metrics._task_duration``/``_task_cost`` exactly for
    the normalized figures (so ``flow_analysis`` reproduces the already
    validated cycle-time/cost numbers), and additionally computes the raw
    (mixed-currency, uncorrected) cost from each RACI entry's ``raw_rate``,
    and the value-adding share of this task's own time.
    """
    duration = (attrs.get("process_time") or 0) + (attrs.get("rework_time") or 0) + (attrs.get("waiting_time") or 0)
    duration_hours = duration / MINUTES_PER_HOUR

    cost_norm = 0.0
    cost_raw = 0.0
    for entry in attrs.get("raci") or []:
        pct = float(entry.get("pct") or 0) / 100.0
        cost_norm += duration_hours * float(entry.get("hourly_rate") or 0) * pct
        cost_raw += duration_hours * float(entry.get("raw_rate") or 0) * pct

    cost_norm += (attrs.get("extra_cost") or 0.0)
    cost_raw += (attrs.get("extra_cost_raw") or 0.0)

    va_time = duration if attrs.get("value_classification") == "VA" else 0.0

    return FlowValue(duration, va_time, cost_raw, cost_norm)


# ---------------------------------------------------------------------------
# Back-edge (rework loop) detection and folding.
#
# Loops are resolved as a preprocessing pass that rewrites the graph into an
# acyclic one before the main walk, rather than interleaving loop math into
# the walk itself: this keeps the Sequential/Conditional/Parallel walker
# simple (and independently testable against the already-validated
# numbers) while still handling arbitrary simple rework loops generically.
# Nested/overlapping loops are resolved innermost-first by re-detecting
# after every fold; pathologically interleaved loop structures are out of
# scope, mirroring the project's existing KNOWN_LIMITATIONS.md posture.
# ---------------------------------------------------------------------------


def _out_edges_with_probability(g: nx.DiGraph, node) -> list:
    """Return [(target, probability, condition)] for a node's outgoing
    branches, preferring the gateway's explicit ``branches`` list (the
    source of truth - see ``app.core.parser.build_graph``) and falling back
    to raw graph edges for non-gateway nodes."""
    branches = g.nodes[node].get("branches")
    if branches is not None:
        return [(b["target"], b.get("probability") or 0.0, b.get("condition")) for b in branches]
    return [(v, a.get("probability") or 0.0, a.get("condition")) for _, v, a in g.out_edges(node, data=True)]


def _find_back_edge(g: nx.DiGraph, start_node: str = "START"):
    """DFS from ``start_node``; returns (u, v) for the first edge found
    where v is an ancestor of u on the current DFS path (a back edge), or
    None if the graph is already acyclic from ``start_node``."""
    visited: set = set()
    on_stack: set = set()
    found = [None]

    def dfs(node):
        if found[0] is not None:
            return
        visited.add(node)
        on_stack.add(node)
        for v, _p, _c in _out_edges_with_probability(g, node):
            if found[0] is not None:
                return
            if v in on_stack:
                found[0] = (node, v)
                return
            if v not in visited:
                dfs(v)
        on_stack.discard(node)

    dfs(start_node)
    return found[0]


def _reroute_target(g: nx.DiGraph, old_target, new_target) -> None:
    """Redirect every edge/gateway-branch pointing at ``old_target`` to
    ``new_target`` instead, so ``old_target`` (and anything only reachable
    through it) becomes unreachable from START without needing to delete
    the now-dead nodes - the walker only ever visits reachable nodes."""
    for pred in list(g.predecessors(old_target)):
        attrs = g.get_edge_data(pred, old_target) or {}
        g.remove_edge(pred, old_target)
        g.add_edge(pred, new_target, **attrs)
        branches = g.nodes[pred].get("branches")
        if branches:
            for b in branches:
                if b.get("target") == old_target:
                    b["target"] = new_target


def _fold_back_edge(g: nx.DiGraph, u, v) -> nx.DiGraph:
    """Resolve one rework loop: ``u -> v`` is a back edge (v is an ancestor
    of u), where ``u`` must be a gateway so its branch to ``v`` carries the
    loop-back probability. Returns a new graph with the whole v..u loop
    body collapsed into a single synthetic node carrying the Repetition
    formula's result, wired to continue into whatever ``u``'s non-looping
    branch(es) led to (renormalized so they sum to 1, since the loop's
    expected repetition is already fully accounted for by that point).
    """
    if g.nodes[u].get("kind") != "gateway":
        raise ValueError(
            f"Back edge {u!r} -> {v!r} does not originate from a gateway, so no branch "
            "probability is available to apply the Repetition (loop) formula."
        )

    branches = _out_edges_with_probability(g, u)
    loop_p = next((p for target, p, _c in branches if target == v), 0.0)
    exit_branches = [(target, p, c) for target, p, c in branches if target != v]
    if not exit_branches:
        raise ValueError(f"Gateway {u!r} has no branch other than the loop-back to {v!r}: the loop never exits.")

    # Single pass through the body (v..u), treating u as a sink so the
    # ordinary acyclic walker below can compute it without recursing back
    # into the loop it's currently helping to resolve.
    body_graph = g.copy()
    for target, _p, _c in branches:
        if body_graph.has_edge(u, target):
            body_graph.remove_edge(u, target)
    body_graph.nodes[u]["branches"] = []
    body_value = _walk_acyclic(body_graph, v)
    looped = _repetition(body_value, loop_p)

    g2 = g.copy()
    fold_id = f"__loop_fold__{v}__{u}__{next(_FOLD_COUNTER)}"
    exit_total_p = sum(p for _t, p, _c in exit_branches) or 1.0
    renormalized = [
        {"target": target, "condition": c, "probability": p / exit_total_p} for target, p, c in exit_branches
    ]
    g2.add_node(fold_id, kind="gateway", gateway_type="EXCLUSIVE", name=f"(resolved loop {v}->{u})",
                branches=renormalized, precomputed_flow_value=looped.as_tuple())
    _reroute_target(g2, v, fold_id)
    return g2


_FOLD_COUNTER = count()


def resolve_loops(g: nx.DiGraph, start_node: str = "START", max_folds: int = 1000) -> nx.DiGraph:
    """Return a copy of ``g`` with every rework loop reachable from
    ``start_node`` collapsed via the Repetition formula, so the result is
    guaranteed acyclic from ``start_node`` and safe for the ordinary
    Sequential/Conditional/Parallel walker.

    No-op (returns an unchanged copy) when the graph has no back edges,
    which is the case for every process definition validated against this
    module so far - loop handling exists for generality, not because the
    sample data exercises it.
    """
    g = g.copy()
    for _ in range(max_folds):
        back_edge = _find_back_edge(g, start_node)
        if back_edge is None:
            return g
        u, v = back_edge
        g = _fold_back_edge(g, u, v)
    raise ValueError("Could not resolve all rework loops within max_folds iterations; graph may be malformed.")


# ---------------------------------------------------------------------------
# Acyclic walker: Sequential + Conditional + Parallel patterns.
# ---------------------------------------------------------------------------


def _walk_acyclic(g: nx.DiGraph, start_node, memo: Optional[dict] = None) -> FlowValue:
    """Backward memoized walk over an already-acyclic graph (post
    ``resolve_loops``), applying the Sequential, Conditional, and Parallel
    patterns. Raises if it detects a node still being computed (a residual
    cycle), rather than recursing infinitely.
    """
    if memo is None:
        memo = {}
    in_progress: set = set()

    def walk(node):
        if node in memo:
            return memo[node]
        if node in in_progress:
            raise ValueError(f"Unresolved cyclic structure at node {node!r}; call resolve_loops() first.")
        in_progress.add(node)

        kind = g.nodes[node].get("kind")
        if node == "END" or kind == "end":
            result = _ZERO
        elif kind in ("task", "precomputed"):
            if "precomputed_flow_value" in g.nodes[node]:
                own = FlowValue(*g.nodes[node]["precomputed_flow_value"])
            else:
                own = _task_flow_value(g.nodes[node])
            successors = list(g.successors(node))
            result = own if not successors else _seq(own, walk(successors[0]))
        elif kind == "gateway":
            gtype = (g.nodes[node].get("gateway_type") or "").upper()
            own = FlowValue(*g.nodes[node]["precomputed_flow_value"]) if "precomputed_flow_value" in g.nodes[node] else _ZERO
            edges = _out_edges_with_probability(g, node)
            if not edges:
                result = own
            elif gtype in PARALLEL_GATEWAYS:
                result = _seq(own, _parallel([walk(t) for t, _p, _c in edges]))
            else:
                result = _seq(own, _conditional([(p, walk(t)) for t, p, _c in edges]))
        elif kind == "start":
            successors = list(g.successors(node))
            result = walk(successors[0]) if successors else _ZERO
        else:
            result = _ZERO

        in_progress.discard(node)
        memo[node] = result
        return result

    return walk(start_node)


def reachability_probabilities(g: nx.DiGraph, start_node: str = "START") -> dict:
    """Forward DP: probability that a random process instance executes each
    node, following gateway branch probabilities (XOR/inclusive fan out a
    fraction of the parent's probability; parallel/AND branches each
    inherit the parent's probability in full, since every branch executes).

    Requires ``g`` to already be acyclic (see ``resolve_loops``); a node
    with a nonzero loop factor baked in via ``resolve_loops`` will show up
    here as extra *expected occurrences* on the folded node, not a
    probability in [0, 1] - that's intentional, since a reworked task can
    execute more than once per instance.
    """
    order = list(nx.topological_sort(g))
    prob = {start_node: 1.0}
    for node in order:
        p_node = prob.get(node, 0.0)
        if p_node == 0.0:
            continue
        kind = g.nodes[node].get("kind")
        if kind == "gateway":
            gtype = (g.nodes[node].get("gateway_type") or "").upper()
            edges = _out_edges_with_probability(g, node)
            for target, p, _c in edges:
                inherited = p_node if gtype in PARALLEL_GATEWAYS else p_node * p
                prob[target] = prob.get(target, 0.0) + inherited
        else:
            for target in g.successors(node):
                prob[target] = prob.get(target, 0.0) + p_node
    return prob


# ---------------------------------------------------------------------------
# 1. Flow Analysis (Cycle Time Law).
# ---------------------------------------------------------------------------


def flow_analysis(g: nx.DiGraph, start_node: str = "START") -> dict:
    """Chapter 7 Flow Analysis: expected cycle time via the Cycle Time Law,
    classifying every construct in the graph as Sequential, Parallel,
    Conditional, or Repetition and applying that pattern's formula.

    Returns cycle time plus the value-add/cost breakdown needed by
    ``cycle_time_efficiency`` and ``cost_analysis``, all computed in one
    graph walk so every derived metric is consistent with the same
    probability weighting.
    """
    acyclic = resolve_loops(g, start_node)
    fv = _walk_acyclic(acyclic, start_node)
    return {
        "cycle_time_minutes": round(fv.time, 2),
        "value_add_minutes": round(fv.va_time, 2),
        "non_value_add_minutes": round(fv.time - fv.va_time, 2),
        "cost_raw": round(fv.cost_raw, 2),
        "cost_normalized": round(fv.cost_norm, 2),
    }


# ---------------------------------------------------------------------------
# 2. Cycle Time Efficiency.
# ---------------------------------------------------------------------------


def cycle_time_efficiency(flow: dict) -> float:
    """CTE = value-adding time / total cycle time, as a percentage.

    Takes the dict returned by ``flow_analysis`` so CTE is always computed
    from the exact same cycle-time/value-add figures reported elsewhere.
    """
    total = flow["cycle_time_minutes"]
    if total <= 0:
        return 0.0
    return round(flow["value_add_minutes"] / total * 100, 2)


# ---------------------------------------------------------------------------
# 3. Cost Analysis (Activity-Based Costing).
# ---------------------------------------------------------------------------


def cost_analysis(g: nx.DiGraph, start_node: str = "START") -> dict:
    """Activity-Based Costing rolled up through the probability-weighted
    graph: per-task resource cost (hourlyRate x allocation% x duration)
    plus ``extra_cost``, summed via the same Sequential/Conditional/
    Parallel/Repetition composition used for cycle time.

    Returns both the raw (mixed-currency, uncorrected) total - kept only
    for backward comparison against numbers computed before the FX fix -
    and the currency-normalized total. There is no fixed/overhead cost
    field anywhere in the schema, so every dollar here is variable
    (resource-time-driven) cost.
    """
    flow = flow_analysis(g, start_node)
    return {"cost_raw": flow["cost_raw"], "cost_normalized": flow["cost_normalized"]}


# ---------------------------------------------------------------------------
# 4. Resource Utilization & Bottleneck Analysis (Little's Law).
# ---------------------------------------------------------------------------


def _weeks_per_occurrence(frequency_interval, frequency_period, occurrences) -> Optional[float]:
    """Convert a task's frequency_interval/frequency_period/occurrences into
    instances-per-week. Returns None when frequency data is missing (the
    caller then excludes that task from utilization, since no meaningful
    arrival rate can be derived for it)."""
    if frequency_interval in (None, 0) or not frequency_period:
        return None
    try:
        occ = float(occurrences) if occurrences not in (None, "") else 1.0
    except (TypeError, ValueError):
        occ = 1.0
    weeks_per_interval = _PERIOD_TO_WEEKS.get(str(frequency_period).upper())
    if weeks_per_interval is None:
        return None
    weeks_per_cycle = float(frequency_interval) * weeks_per_interval
    if weeks_per_cycle <= 0:
        return None
    return occ / weeks_per_cycle  # instances per week


def process_instance_frequency_per_week(g: nx.DiGraph) -> float:
    """Process instance arrival rate (lambda), instances/week.

    Every task in a well-formed process shares the same process-level
    frequency (frequency_interval/frequency_period/occurrences live on the
    task record in this schema, but describe how often the *process* runs,
    not the individual task). Takes the value from the first reachable
    task in topological order and uses it as the process-wide rate; see
    README.md for why this is a reasonable assumption for this schema.
    """
    order = list(nx.topological_sort(g))
    for node in order:
        if g.nodes[node].get("kind") != "task":
            continue
        rate = _weeks_per_occurrence(
            g.nodes[node].get("frequency_interval"),
            g.nodes[node].get("frequency_period"),
            g.nodes[node].get("occurrences"),
        )
        if rate is not None:
            return rate
    return 0.0


def resource_utilization(g: nx.DiGraph, start_node: str = "START") -> dict:
    """Per-resource (job) required vs. available capacity, utilization
    ratio, ranked bottleneck, and Little's Law WIP estimate.

    Required capacity only counts ``process_time + rework_time`` (actual
    resource-occupying work), not ``expected_waiting_time`` (elapsed
    calendar time a task sits idle, which does not consume a resource's
    hours) - see README.md. Weighted by each task's reachability
    probability (so conditional branches that are rarely taken don't
    inflate a resource's required capacity) and by the process's instance
    arrival rate.
    """
    acyclic = resolve_loops(g, start_node)
    probs = reachability_probabilities(acyclic, start_node)
    lam = process_instance_frequency_per_week(g)

    required_by_job: dict = {}
    job_meta: dict = {}
    for node, attrs in acyclic.nodes(data=True):
        if attrs.get("kind") not in ("task", "precomputed"):
            continue
        p = probs.get(node, 0.0)
        if p <= 0:
            continue
        work_minutes = (attrs.get("process_time") or 0) + (attrs.get("rework_time") or 0)
        for entry in attrs.get("raci") or []:
            job_id = entry.get("job_id")
            if job_id is None:
                continue
            pct = float(entry.get("pct") or 0) / 100.0
            required_minutes = p * lam * work_minutes * pct
            required_by_job[job_id] = required_by_job.get(job_id, 0.0) + required_minutes
            if job_id not in job_meta:
                hours_per_day = float(entry.get("hours_per_day") or 0)
                days_per_week = float(entry.get("days_per_week") or 0)
                buffer_pct = float(entry.get("capacity_buffer") or 0) / 100.0
                available_minutes = hours_per_day * days_per_week * MINUTES_PER_HOUR * (1 - buffer_pct)
                job_meta[job_id] = {
                    "job_id": job_id,
                    "job_name": entry.get("job_name"),
                    "available_minutes_per_week": round(available_minutes, 2),
                }

    resources = []
    for job_id, required in required_by_job.items():
        meta = job_meta[job_id]
        available = meta["available_minutes_per_week"]
        # available == 0 means this job has no recorded capacity (missing
        # hours_per_day/days_per_week) - utilization is genuinely unknown,
        # not infinite. float("inf") would serialize to the bare token
        # `Infinity` in JSON, which is invalid per RFC 8259 and gets
        # rejected by strict parsers (e.g. JS `JSON.parse`); `None` reports
        # "can't be computed" honestly instead.
        utilization = round(required / available * 100, 2) if available > 0 else None
        resources.append({
            "job_id": job_id,
            "job_name": meta["job_name"],
            "required_minutes_per_week": round(required, 2),
            "available_minutes_per_week": available,
            "utilization_percent": utilization,
        })
    resources.sort(key=lambda r: (r["utilization_percent"] is None, -(r["utilization_percent"] or 0)))

    bottleneck = (
        {"job_id": resources[0]["job_id"], "job_name": resources[0]["job_name"],
         "utilization_percent": resources[0]["utilization_percent"]}
        if resources else {"job_id": None, "job_name": None, "utilization_percent": 0.0}
    )

    cycle_time_minutes = _walk_acyclic(acyclic, start_node).time
    cycle_time_weeks = cycle_time_minutes / MINUTES_PER_WEEK
    avg_wip = round(lam * cycle_time_weeks, 4)

    return {
        "resource_utilization": resources,
        "bottleneck": bottleneck,
        "avg_wip": avg_wip,
        "arrival_rate_per_week": round(lam, 4),
    }


# ---------------------------------------------------------------------------
# 5. Before/After Comparison Report.
# ---------------------------------------------------------------------------


def _full_analysis(g: nx.DiGraph) -> dict:
    """Run every Chapter 7 technique against one graph and shape the result
    to match the ``as_is_flow_analysis``/``to_be_flow_analysis`` contract."""
    flow = flow_analysis(g)
    util = resource_utilization(g)
    cte = cycle_time_efficiency(flow)
    return {
        "cycle_time_minutes": flow["cycle_time_minutes"],
        "cost": flow["cost_raw"],
        "cost_currency_normalized": flow["cost_normalized"],
        "cycle_time_efficiency_percent": cte,
        "value_add_minutes": flow["value_add_minutes"],
        "non_value_add_minutes": flow["non_value_add_minutes"],
        "avg_wip": util["avg_wip"],
        "resource_utilization": util["resource_utilization"],
        "bottleneck": util["bottleneck"],
    }


def percent_improvement(before: float, after: float) -> float:
    """Positive means improvement (after < before for cost/time/WIP, or
    after > before for CTE - callers pass operands accordingly)."""
    if before == 0:
        return 0.0
    return round((before - after) / before * 100, 2)


DEFAULT_SEED = 42


def _full_heuristic_sequence(baseline_graph: nx.DiGraph, applied_steps: list) -> list:
    """Every registered heuristic (see ``app.core.heuristics.HEURISTICS``),
    not just the ones the redesign search picked - so a frontend can render
    a fixed 10-row checklist of what was considered, rather than only what
    happened.

    Applied heuristics carry their execution position (``step_order``,
    1-based) alongside the target/description ``replay_sequence`` already
    produced; a heuristic applied more than once (e.g. ``extra_resources``
    on two different tasks) gets one row per application. Heuristics never
    applied get a single row explaining why: whether the baseline process
    had any valid target for that heuristic at all (``candidates_available``)
    distinguishes "the search chose not to use this" from "this heuristic
    doesn't apply to this process's structure."
    """
    candidate_hids = {hid for hid, _target in all_candidates(baseline_graph)}
    applied_by_hid: dict = {}
    for i, step in enumerate(applied_steps, 1):
        applied_by_hid.setdefault(step["heuristic_id"], []).append((i, step))

    entries = []
    for hid in HEURISTICS:
        instances = applied_by_hid.get(hid, [])
        if instances:
            for step_order, step in instances:
                entries.append({
                    "heuristic_id": hid,
                    "applied": True,
                    "step_order": step_order,
                    "target": list(step["target"]),
                    "description": step["description"],
                })
        else:
            had_candidates = hid in candidate_hids
            entries.append({
                "heuristic_id": hid,
                "applied": False,
                "step_order": None,
                "target": None,
                "description": (
                    "Candidates were available on this process but were not selected by the redesign search."
                    if had_candidates
                    else "No applicable candidates found in this process."
                ),
            })
    return entries


def analyze_before_after(baseline_graph: nx.DiGraph, final_graph: nx.DiGraph) -> tuple:
    """Run every Chapter 7 technique against both graphs and compute the
    before/after improvement deltas, in one place.

    Shared by ``compare()`` and ``app.services.redesign_service.redesign()``
    so both the CLI report and the live ``POST /redesign`` response report
    identical flow-analysis/CTE/cost/utilization/WIP numbers for the same
    graphs, computed by the same code path, instead of each assembling its
    own before/after dict and risking drift between them.

    Returns ``(as_is_analysis, to_be_analysis, improvement)``. Each
    analysis dict carries both ``cost`` (raw, mixed-currency, uncorrected -
    see ``QUANTITATIVE_ANALYSIS.md``) and ``cost_currency_normalized``;
    ``improvement.cost_percent`` is computed from the raw figure to match
    ``compare()``'s established contract. A caller that surfaces
    ``cost_currency_normalized`` as its own "cost" field (as
    ``redesign_service.redesign()`` does, to preserve the live endpoint's
    already-correct currency-normalized behavior) should compute its own
    cost-improvement percentage from that field instead of reusing this
    one.
    """
    as_is_analysis = _full_analysis(baseline_graph)
    to_be_analysis = _full_analysis(final_graph)

    cte_before = as_is_analysis["cycle_time_efficiency_percent"]
    cte_after = to_be_analysis["cycle_time_efficiency_percent"]
    # Positive means CTE improved (went up), unlike percent_improvement's
    # before-after convention (which is positive when a value went down) -
    # CTE improving is an increase, so the sign has to flip relative to
    # cost/cycle-time/WIP.
    cte_change = round((cte_after - cte_before) / cte_before * 100, 2) if cte_before else 0.0
    bottleneck_shifted = (
        as_is_analysis["bottleneck"]["job_id"] is not None
        and to_be_analysis["bottleneck"]["job_id"] is not None
        and as_is_analysis["bottleneck"]["job_id"] != to_be_analysis["bottleneck"]["job_id"]
    )

    improvement = {
        "cycle_time_percent": percent_improvement(
            as_is_analysis["cycle_time_minutes"], to_be_analysis["cycle_time_minutes"]
        ),
        "cost_percent": percent_improvement(as_is_analysis["cost"], to_be_analysis["cost"]),
        "cte_percent_change": cte_change,
        "avg_wip_percent_change": percent_improvement(as_is_analysis["avg_wip"], to_be_analysis["avg_wip"]),
        "bottleneck_shifted": bottleneck_shifted,
    }
    return as_is_analysis, to_be_analysis, improvement


def compare(as_is_path: "str", seed: Optional[int] = DEFAULT_SEED) -> dict:
    """Run the full Chapter 7 quantitative-analysis suite on ``as_is_path``
    and the RL-redesigned process derived from it, and assemble the
    before/after comparison report.

    The to-be process is not a second hand-authored file: this project's
    redesign engine (``app.core.trainer``/``app.core.heuristics``) searches
    for a good heuristic sequence and produces the to-be graph from the
    as-is graph directly, so that pipeline is reused here rather than
    duplicated. Cycle-time-optimal sequences aren't always unique, so an
    unseeded run can land on a different (equally cycle-time-optimal, but
    not necessarily equally cheap) sequence each time; ``seed`` defaults to
    a fixed value so ``compare()`` is reproducible run-to-run - pass
    ``None`` to restore the fully stochastic behavior ``POST /redesign``
    uses. Returns a dict matching the required JSON output contract; call
    ``to_markdown`` on the result for the human-readable report.
    """
    as_is_data = load_process(as_is_path)
    validate_process_definition(as_is_data)

    baseline_graph = build_graph(as_is_data)
    validate_graph_reachability(baseline_graph)
    baseline_metrics = compute_metrics_for_training(baseline_graph)

    _, best_sequence, _best_final_metrics, _ = train(baseline_graph, baseline_metrics, seed=seed)
    final_graph, steps = replay_sequence(baseline_graph, best_sequence or [])
    to_be_process_json = serialize_graph(final_graph, as_is_data)

    as_is_analysis, to_be_analysis, improvement = analyze_before_after(baseline_graph, final_graph)
    sequence = _full_heuristic_sequence(baseline_graph, steps)

    return {
        "process_id": as_is_data.get("process_id"),
        "process_code": as_is_data.get("process_code"),
        "process_name": as_is_data.get("process_name"),
        "as_is_flow_analysis": as_is_analysis,
        "to_be_flow_analysis": to_be_analysis,
        "improvement": improvement,
        "sequence": sequence,
        "to_be_process_json": to_be_process_json,
    }


def compute_metrics_for_training(g: nx.DiGraph) -> dict:
    """The RL trainer's reward function needs the same fast (non-loop-
    resolving) metrics ``app.core.metrics.compute_metrics`` already
    provides - importing it locally avoids a module-level circular import
    with ``app.core.environment``."""
    from app.core.metrics import compute_metrics

    return compute_metrics(g)


def to_markdown(report: dict) -> str:
    """Render a ``compare()`` result as a human-readable Markdown report:
    as-is -> to-be -> % change for every metric, plus a short narrative
    flagging anything counterintuitive."""
    a = report["as_is_flow_analysis"]
    b = report["to_be_flow_analysis"]
    imp = report["improvement"]

    def row(label, before, after, pct, unit=""):
        return f"| {label} | {before}{unit} | {after}{unit} | {pct:+.2f}% |"

    lines = [
        f"# Quantitative Process Analysis: {report['process_name']} ({report['process_code']})",
        "",
        "## Before / After Comparison",
        "",
        "| Metric | As-Is | To-Be | Change |",
        "|---|---|---|---|",
        row("Cycle time (minutes)", a["cycle_time_minutes"], b["cycle_time_minutes"], imp["cycle_time_percent"]),
        row("Cost (raw, mixed-currency)", a["cost"], b["cost"], imp["cost_percent"]),
        row("Cost (currency-normalized)", a["cost_currency_normalized"], b["cost_currency_normalized"],
            percent_improvement(a["cost_currency_normalized"], b["cost_currency_normalized"])),
        row("Cycle Time Efficiency", a["cycle_time_efficiency_percent"], b["cycle_time_efficiency_percent"],
            imp["cte_percent_change"], unit="%"),
        row("Value-adding minutes", a["value_add_minutes"], b["value_add_minutes"],
            percent_improvement(a["value_add_minutes"], b["value_add_minutes"])),
        row("Non-value-adding minutes", a["non_value_add_minutes"], b["non_value_add_minutes"],
            percent_improvement(a["non_value_add_minutes"], b["non_value_add_minutes"])),
        row("Avg. WIP (Little's Law)", a["avg_wip"], b["avg_wip"], imp["avg_wip_percent_change"]),
        "",
        "## Bottleneck Resource",
        "",
        f"- As-Is: **{a['bottleneck']['job_name']}** at {a['bottleneck']['utilization_percent']}% utilization",
        f"- To-Be: **{b['bottleneck']['job_name']}** at {b['bottleneck']['utilization_percent']}% utilization",
        f"- Bottleneck shifted to a different resource: {'yes' if imp['bottleneck_shifted'] else 'no'}",
        "",
        "## Resource Utilization (As-Is, ranked)",
        "",
        "| Job | Required min/week | Available min/week | Utilization |",
        "|---|---|---|---|",
    ]
    for r in a["resource_utilization"]:
        lines.append(
            f"| {r['job_name']} | {r['required_minutes_per_week']} | {r['available_minutes_per_week']} "
            f"| {r['utilization_percent']}% |"
        )

    applied = sorted((s for s in report["sequence"] if s["applied"]), key=lambda s: s["step_order"])

    lines += ["", "## Redesign Sequence Applied", ""]
    if applied:
        for step in applied:
            lines.append(f"{step['step_order']}. **{step['heuristic_id']}** - {step['description']}")
    else:
        lines.append("No heuristics improved on the baseline; as-is and to-be are identical.")

    lines += ["", "## Heuristics Considered (all 10)", ""]
    lines += ["| Heuristic | Applied | Notes |", "|---|---|---|"]
    for s in report["sequence"]:
        mark = "✅" if s["applied"] else "✖️"
        note = s["description"] if not s["applied"] else f"step {s['step_order']}"
        lines.append(f"| {s['heuristic_id']} | {mark} | {note} |")

    lines += ["", "## Notes", ""]
    notes = []
    va_before, va_after = a["value_add_minutes"], b["value_add_minutes"]
    nva_before, nva_after = a["non_value_add_minutes"], b["non_value_add_minutes"]
    nva_removed = nva_before - nva_after
    va_change = va_after - va_before
    total_removed = (a["cycle_time_minutes"] - b["cycle_time_minutes"])
    if total_removed > 0:
        nva_share = max(0.0, nva_removed) / total_removed * 100
        notes.append(
            f"Of the {total_removed:.2f}-minute cycle-time reduction, "
            f"{nva_share:.1f}% came from eliminating/reducing non-value-adding time "
            f"and the remainder from speeding up value-adding work ({va_change:+.2f} VA minutes)."
        )
    if imp["cte_percent_change"] < 0:
        notes.append(
            "CTE got worse despite the overall redesign - the cycle time dropped, but value-adding time dropped "
            "proportionally more, so a smaller share of the (shorter) process is now value-adding."
        )
    if imp["bottleneck_shifted"]:
        notes.append(
            f"The bottleneck shifted from {a['bottleneck']['job_name']} to {b['bottleneck']['job_name']} "
            "rather than disappearing - relieving one resource exposed the next-most-loaded one."
        )
    if imp["cost_percent"] < 0:
        notes.append("Cost got worse despite the redesign - check the sequence for cost-increasing heuristics.")
    if not notes:
        notes.append("No counterintuitive results: every metric moved in the expected direction.")
    lines.extend(f"- {n}" for n in notes)

    return "\n".join(lines) + "\n"
