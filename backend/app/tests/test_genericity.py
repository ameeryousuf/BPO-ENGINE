"""Verifies the redesign pipeline runs successfully across multiple, differently-shaped process definitions."""

import pytest

from app.services import redesign_service

PROCESS_FIXTURES = ["as_is_process", "second_process"]


@pytest.mark.parametrize("fixture_name", PROCESS_FIXTURES)
def test_redesign_pipeline_succeeds_on_process(request, fixture_name):
    process_data = request.getfixturevalue(fixture_name)
    result = redesign_service.redesign(process_data)

    assert result["before"]["cycle_time_minutes"] > 0
    assert result["after"]["cycle_time_minutes"] <= result["before"]["cycle_time_minutes"]
    assert result["after"]["cost"] <= result["before"]["cost"]
