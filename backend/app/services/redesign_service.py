"""Orchestrates the end-to-end business process redesign pipeline.

This is the single entry point the API layer calls. It knows nothing
about HTTP; it takes a parsed process definition and returns a plain dict
matching the public response shape. Everything happens in memory - no
files are read or written.
"""

import logging

from app.core.metrics import compute_metrics
from app.core.parser import build_graph, validate_graph_reachability, validate_process_definition
from app.core.quantitative_analysis import analyze_before_after, percent_improvement
from app.core.replay import replay_sequence, serialize_graph
from app.core.trainer import train
from app.exceptions import RedesignIntegrityError

logger = logging.getLogger(__name__)

# How far metrics.compute_metrics() (the RL trainer's fast reward signal)
# may disagree with quantitative_analysis.flow_analysis() (the fuller
# Chapter 7 suite) for the same graph before it's treated as a real
# divergence bug rather than floating-point rounding noise between the two
# independently-implemented graph walks. Verified empirically at 0.0 exact
# agreement across both sample fixtures and several post-heuristic graph
# shapes before this was wired in; a small tolerance guards against
# legitimate rounding-order differences without masking a genuine bug.
_METRICS_AGREEMENT_TOLERANCE = 0.05


def _as_live_metrics(analysis: dict) -> dict:
    """Reshape a quantitative_analysis flow-analysis dict for the live
    ``POST /redesign`` response.

    ``cost`` here is the currency-normalized figure, matching this
    endpoint's existing, already-correct behavior (see
    ``KNOWN_LIMITATIONS.md``) - not quantitative_analysis's raw,
    mixed-currency ``cost``, which exists only to reproduce historically
    validated thesis figures for ``compare()``/``report.py`` and has no
    place in a live API response.
    """
    live = dict(analysis)
    live["cost"] = live.pop("cost_currency_normalized")
    return live


def _check_metrics_agree(label: str, rl_metrics: dict, analysis: dict) -> None:
    ct_diff = abs(rl_metrics["cycle_time_minutes"] - analysis["cycle_time_minutes"])
    cost_diff = abs(rl_metrics["cost"] - analysis["cost_currency_normalized"])
    if ct_diff > _METRICS_AGREEMENT_TOLERANCE or cost_diff > _METRICS_AGREEMENT_TOLERANCE:
        raise RedesignIntegrityError(
            f"{label} quantitative-analysis figures (cycle_time={analysis['cycle_time_minutes']}, "
            f"cost={analysis['cost_currency_normalized']}) do not match RL trainer metrics "
            f"{rl_metrics} for the same graph (diff ct={ct_diff}, cost={cost_diff})."
        )


def redesign(process_data: dict) -> dict:
    """Run the full redesign pipeline on a process definition.

    Steps: validate the input shape, parse it into a graph, train the RL
    agent to find a good heuristic sequence, replay that sequence for a
    reproducible final graph, verify its metrics match what training
    reported, and serialize the result back into process JSON. ``before``
    and ``after`` carry the full Chapter 7 quantitative-analysis suite -
    flow analysis, Cycle Time Efficiency, resource utilization, Little's
    Law/avg WIP, and bottleneck detection (see
    ``app.core.quantitative_analysis`` and ``QUANTITATIVE_ANALYSIS.md``) -
    not just cycle time and cost.

    Raises ``InvalidProcessDefinitionError`` if ``process_data`` is
    malformed, and ``RedesignIntegrityError`` if replay produces metrics
    inconsistent with training, or if the quantitative-analysis suite's
    numbers disagree with the RL trainer's own metrics for the same graph
    beyond floating-point rounding noise (indicates the two independent
    implementations have drifted apart - a bug, not bad input).
    """
    validate_process_definition(process_data)

    baseline_graph = build_graph(process_data)
    validate_graph_reachability(baseline_graph)
    baseline_metrics = compute_metrics(baseline_graph)

    _, best_sequence, best_final_metrics, _ = train(baseline_graph, baseline_metrics)
    best_sequence = best_sequence or []

    final_graph, steps = replay_sequence(baseline_graph, best_sequence)
    final_metrics = compute_metrics(final_graph)

    if final_metrics != best_final_metrics:
        raise RedesignIntegrityError(
            f"Replayed metrics {final_metrics} do not match trainer-reported metrics {best_final_metrics}"
        )

    as_is_analysis, to_be_analysis, improvement = analyze_before_after(baseline_graph, final_graph)
    _check_metrics_agree("baseline", baseline_metrics, as_is_analysis)
    _check_metrics_agree("final", final_metrics, to_be_analysis)

    before = _as_live_metrics(as_is_analysis)
    after = _as_live_metrics(to_be_analysis)
    improvement = dict(improvement)
    improvement["cost_percent"] = percent_improvement(before["cost"], after["cost"])

    to_be_process = serialize_graph(final_graph, process_data)

    logger.info(
        "Redesign complete: before(cycle_time=%s, cost=%s) after(cycle_time=%s, cost=%s) steps=%d",
        before["cycle_time_minutes"], before["cost"],
        after["cycle_time_minutes"], after["cost"], len(steps),
    )

    return {
        "before": before,
        "after": after,
        "improvement": improvement,
        "sequence": steps,
        "toBeProcess": to_be_process,
    }
