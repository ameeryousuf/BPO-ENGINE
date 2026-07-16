"""Pydantic response models for the public API."""

from typing import Any, Optional, Union

from pydantic import BaseModel


class ResourceUtilizationEntry(BaseModel):
    """One resource's required vs. available capacity for a process."""

    job_id: int
    job_name: Optional[str] = None
    required_minutes_per_week: float
    available_minutes_per_week: float
    # None when the job has no recorded capacity (missing hours_per_day/
    # days_per_week) - utilization is genuinely unknown, not infinite or
    # zero. See app.core.quantitative_analysis.resource_utilization.
    utilization_percent: Optional[float] = None


class Bottleneck(BaseModel):
    """The most-utilized resource, if any resource data was available."""

    job_id: Optional[int] = None
    job_name: Optional[str] = None
    utilization_percent: Optional[float] = None


class Metrics(BaseModel):
    """Chapter 7 quantitative-analysis suite for a process graph: flow
    analysis (cycle time, value-add split), Cycle Time Efficiency, cost,
    resource utilization, and Little's Law (avg WIP) - see
    app.core.quantitative_analysis and QUANTITATIVE_ANALYSIS.md."""

    cycle_time_minutes: float
    cost: float
    cycle_time_efficiency_percent: float
    value_add_minutes: float
    non_value_add_minutes: float
    avg_wip: float
    resource_utilization: list[ResourceUtilizationEntry]
    bottleneck: Bottleneck


class Improvement(BaseModel):
    """Percentage improvement of the redesigned process over the baseline."""

    cycle_time_percent: float
    cost_percent: float
    cte_percent_change: float
    avg_wip_percent_change: float
    bottleneck_shifted: bool


class RedesignStep(BaseModel):
    """A single heuristic applied during redesign, in human-readable form."""

    heuristic_id: str
    target: list[Union[int, str]]
    description: str


class RedesignResponse(BaseModel):
    """Response body for ``POST /redesign``."""

    before: Metrics
    after: Metrics
    improvement: Improvement
    sequence: list[RedesignStep]
    toBeProcess: dict[str, Any]
