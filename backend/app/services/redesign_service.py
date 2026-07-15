"""Orchestrates the end-to-end business process redesign pipeline.

This is the single entry point the API layer calls. It knows nothing
about HTTP; it takes a parsed process definition and returns a plain dict
matching the public response shape. Everything happens in memory - no
files are read or written.
"""

import logging

from app.core.metrics import compute_metrics
from app.core.parser import build_graph, validate_process_definition
from app.core.replay import replay_sequence, serialize_graph
from app.core.trainer import train
from app.exceptions import RedesignIntegrityError

logger = logging.getLogger(__name__)


def _percent_improvement(before: float, after: float) -> float:
    if before == 0:
        return 0.0
    return round((before - after) / before * 100, 2)


def redesign(process_data: dict) -> dict:
    """Run the full redesign pipeline on a process definition.

    Steps: validate the input shape, parse it into a graph, train the RL
    agent to find a good heuristic sequence, replay that sequence for a
    reproducible final graph, verify its metrics match what training
    reported, and serialize the result back into process JSON.

    Raises ``InvalidProcessDefinitionError`` if ``process_data`` is
    malformed, and ``RedesignIntegrityError`` if replay produces metrics
    inconsistent with training (indicates a bug, not bad input).
    """
    validate_process_definition(process_data)

    baseline_graph = build_graph(process_data)
    baseline_metrics = compute_metrics(baseline_graph)

    _, best_sequence, best_final_metrics, _ = train(baseline_graph, baseline_metrics)
    best_sequence = best_sequence or []

    final_graph, steps = replay_sequence(baseline_graph, best_sequence)
    final_metrics = compute_metrics(final_graph)

    if final_metrics != best_final_metrics:
        raise RedesignIntegrityError(
            f"Replayed metrics {final_metrics} do not match trainer-reported metrics {best_final_metrics}"
        )

    to_be_process = serialize_graph(final_graph, process_data)

    logger.info(
        "Redesign complete: before=%s after=%s steps=%d",
        baseline_metrics, final_metrics, len(steps),
    )

    return {
        "before": baseline_metrics,
        "after": final_metrics,
        "improvement": {
            "cycle_time_percent": _percent_improvement(
                baseline_metrics["cycle_time_minutes"], final_metrics["cycle_time_minutes"]
            ),
            "cost_percent": _percent_improvement(baseline_metrics["cost"], final_metrics["cost"]),
        },
        "sequence": steps,
        "toBeProcess": to_be_process,
    }
