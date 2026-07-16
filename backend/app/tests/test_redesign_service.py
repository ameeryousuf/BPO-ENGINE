"""Tests for app.services.redesign_service: the full in-memory pipeline."""

import pytest

from app.core.metrics import compute_metrics
from app.core.parser import build_graph
from app.core.quantitative_analysis import flow_analysis
from app.exceptions import InvalidProcessDefinitionError, RedesignIntegrityError
from app.services import redesign_service


def test_redesign_rejects_invalid_process_definition():
    with pytest.raises(InvalidProcessDefinitionError):
        redesign_service.redesign({"not": "a process"})


METRICS_KEYS = {
    "cycle_time_minutes", "cost", "cycle_time_efficiency_percent", "value_add_minutes",
    "non_value_add_minutes", "avg_wip", "resource_utilization", "bottleneck",
}
IMPROVEMENT_KEYS = {
    "cycle_time_percent", "cost_percent", "cte_percent_change", "avg_wip_percent_change", "bottleneck_shifted",
}


def test_redesign_returns_expected_shape(as_is_process):
    """``before``/``after`` carry the full Chapter 7 quantitative-analysis
    suite (flow analysis, CTE, cost, resource utilization, Little's
    Law/avg WIP, bottleneck), not just cycle time and cost - see
    app.core.quantitative_analysis and QUANTITATIVE_ANALYSIS.md."""
    result = redesign_service.redesign(as_is_process)

    assert set(result.keys()) == {"before", "after", "improvement", "sequence", "toBeProcess"}
    assert set(result["before"].keys()) == METRICS_KEYS
    assert set(result["after"].keys()) == METRICS_KEYS
    assert set(result["improvement"].keys()) == IMPROVEMENT_KEYS
    assert isinstance(result["sequence"], list)
    assert isinstance(result["toBeProcess"], dict)

    for metrics in (result["before"], result["after"]):
        assert isinstance(metrics["resource_utilization"], list)
        assert set(metrics["bottleneck"].keys()) == {"job_id", "job_name", "utilization_percent"}
        for entry in metrics["resource_utilization"]:
            assert set(entry.keys()) == {
                "job_id", "job_name", "required_minutes_per_week", "available_minutes_per_week",
                "utilization_percent",
            }


def test_redesign_cost_field_is_currency_normalized_not_raw(as_is_process):
    """``before.cost``/``after.cost`` must stay the currency-normalized
    figure this endpoint has always returned since the FX fix
    (KNOWN_LIMITATIONS.md) - quantitative_analysis.compare()'s raw,
    mixed-currency ``cost`` (kept there only to reproduce historical thesis
    validation numbers) must never leak into the live API's meaning of
    "cost", or every existing consumer of this field silently starts
    reading wrong money.
    """
    result = redesign_service.redesign(as_is_process)
    # The raw (pre-FX-fix, mixed-currency) as-is cost is independently
    # known to be ~39,815.14 (see QUANTITATIVE_ANALYSIS.md); the live
    # endpoint's cost must be the much larger PKR-normalized figure, not
    # that one.
    assert result["before"]["cost"] > 100_000


def test_redesign_after_metrics_do_not_regress_baseline(as_is_process):
    result = redesign_service.redesign(as_is_process)
    assert result["after"]["cycle_time_minutes"] <= result["before"]["cycle_time_minutes"]
    assert result["after"]["cost"] <= result["before"]["cost"]


def test_redesign_to_be_process_preserves_process_identity(as_is_process):
    result = redesign_service.redesign(as_is_process)
    assert result["toBeProcess"]["process_id"] == as_is_process["process_id"]
    assert isinstance(result["toBeProcess"]["process_task"], list)


def test_metrics_compute_metrics_and_flow_analysis_agree_on_as_is_and_second_process(
    as_is_process, second_process
):
    """Regression guard for the two independent Python implementations of
    the Cycle Time Law (metrics.compute_metrics, used by the RL trainer,
    and quantitative_analysis.flow_analysis, used for the fuller Chapter 7
    suite): they must keep computing the same cycle time and normalized
    cost for the same graph. redesign_service.redesign() enforces this at
    runtime too (RedesignIntegrityError) - this test is the same guarantee,
    pinned in CI, on both sample fixtures rather than only surfacing a
    drift as a live 500 error.
    """
    for process in (as_is_process, second_process):
        g = build_graph(process)
        m = compute_metrics(g)
        f = flow_analysis(g)
        assert m["cycle_time_minutes"] == pytest.approx(f["cycle_time_minutes"], abs=0.05)
        assert m["cost"] == pytest.approx(f["cost_normalized"], abs=0.05)


def test_redesign_raises_integrity_error_when_quantitative_analysis_disagrees_with_trainer(
    monkeypatch, as_is_process
):
    """If quantitative_analysis.flow_analysis() ever disagrees with the RL
    trainer's metrics.compute_metrics() by more than rounding noise, the
    endpoint must fail loudly (RedesignIntegrityError -> 500), not silently
    ship mismatched numbers in before/after.
    """
    from app.core import quantitative_analysis

    # Simplest reliable way to force a mismatch: monkeypatch
    # analyze_before_after's underlying _full_analysis call to report a
    # cycle time far off from what the RL trainer computed.
    original_full_analysis = quantitative_analysis._full_analysis

    def _corrupted_full_analysis(g):
        result = original_full_analysis(g)
        result["cycle_time_minutes"] += 10_000
        return result

    monkeypatch.setattr(quantitative_analysis, "_full_analysis", _corrupted_full_analysis)

    with pytest.raises(RedesignIntegrityError):
        redesign_service.redesign(as_is_process)
