"""Pydantic response models for the public API."""

from typing import Any, Union

from pydantic import BaseModel


class Metrics(BaseModel):
    """Expected cycle time and cost for a process graph."""

    cycle_time_minutes: float
    cost: float


class Improvement(BaseModel):
    """Percentage improvement of the redesigned process over the baseline."""

    cycle_time_percent: float
    cost_percent: float


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
