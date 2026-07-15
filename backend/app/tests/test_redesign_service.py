"""Tests for app.services.redesign_service: the full in-memory pipeline."""

import pytest

from app.exceptions import InvalidProcessDefinitionError
from app.services import redesign_service


def test_redesign_rejects_invalid_process_definition():
    with pytest.raises(InvalidProcessDefinitionError):
        redesign_service.redesign({"not": "a process"})


def test_redesign_returns_expected_shape(as_is_process):
    result = redesign_service.redesign(as_is_process)

    assert set(result.keys()) == {"before", "after", "improvement", "sequence", "toBeProcess"}
    assert set(result["before"].keys()) == {"cycle_time_minutes", "cost"}
    assert set(result["after"].keys()) == {"cycle_time_minutes", "cost"}
    assert set(result["improvement"].keys()) == {"cycle_time_percent", "cost_percent"}
    assert isinstance(result["sequence"], list)
    assert isinstance(result["toBeProcess"], dict)


def test_redesign_after_metrics_do_not_regress_baseline(as_is_process):
    result = redesign_service.redesign(as_is_process)
    assert result["after"]["cycle_time_minutes"] <= result["before"]["cycle_time_minutes"]
    assert result["after"]["cost"] <= result["before"]["cost"]


def test_redesign_to_be_process_preserves_process_identity(as_is_process):
    result = redesign_service.redesign(as_is_process)
    assert result["toBeProcess"]["process_id"] == as_is_process["process_id"]
    assert isinstance(result["toBeProcess"]["process_task"], list)
