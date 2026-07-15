"""Tests for app.core.heuristics: candidate discovery and application."""

from app.core.heuristics import HEURISTICS, all_candidates
from app.core.metrics import compute_metrics
from app.core.parser import build_graph


def test_all_candidates_returns_only_registered_heuristic_ids(as_is_process):
    g = build_graph(as_is_process)
    candidates = all_candidates(g)
    assert all(hid in HEURISTICS for hid, _ in candidates)


def test_elimination_apply_reduces_or_maintains_cost_and_removes_task(as_is_process):
    g = build_graph(as_is_process)
    candidates = [t for hid, t in all_candidates(g) if hid == "activity_elimination"]
    if not candidates:
        return
    target = candidates[0]
    _, apply_fn = HEURISTICS["activity_elimination"]
    g2 = apply_fn(g, target)

    (eliminated_node,) = target
    assert eliminated_node not in g2.nodes

    before = compute_metrics(g)
    after = compute_metrics(g2)
    assert after["cycle_time_minutes"] <= before["cycle_time_minutes"]
