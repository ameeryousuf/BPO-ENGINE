"""Tests for app.core.fx: currency conversion to PKR, caching, and fallback."""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import fx
from app.core.parser import build_graph
from app.main import app

DETERMINISTIC_RATES = {"USD": 1.0, "PKR": 278.211558, "EUR": 0.875764, "GBP": 0.747014}


@pytest.fixture(autouse=True)
def reset_fx_cache(monkeypatch):
    """Isolate every test from the real module-level cache and network.

    Without this, whichever test runs first would populate the shared
    in-memory cache (live or fallback) and every later test would silently
    reuse it, making tests order-dependent and occasionally network-flaky.
    """
    monkeypatch.setitem(fx._cache, "rates", None)
    monkeypatch.setitem(fx._cache, "fetched_at", 0.0)
    yield
    monkeypatch.setitem(fx._cache, "rates", None)
    monkeypatch.setitem(fx._cache, "fetched_at", 0.0)


@pytest.fixture
def deterministic_rates(monkeypatch):
    """Pin fx to a known rates table so conversion tests aren't network-dependent."""
    monkeypatch.setattr(fx, "get_rates", lambda force_refresh=False: DETERMINISTIC_RATES)
    return DETERMINISTIC_RATES


def test_convert_to_pkr_passthrough_for_pkr(deterministic_rates):
    assert fx.convert_to_pkr(5000, "PKR") == 5000


def test_convert_to_pkr_usd(deterministic_rates):
    expected = (33 / DETERMINISTIC_RATES["USD"]) * DETERMINISTIC_RATES["PKR"]
    assert fx.convert_to_pkr(33, "USD") == pytest.approx(expected)


def test_convert_to_pkr_eur(deterministic_rates):
    expected = (55 / DETERMINISTIC_RATES["EUR"]) * DETERMINISTIC_RATES["PKR"]
    assert fx.convert_to_pkr(55, "EUR") == pytest.approx(expected)


def test_convert_to_pkr_gbp(deterministic_rates):
    expected = (44 / DETERMINISTIC_RATES["GBP"]) * DETERMINISTIC_RATES["PKR"]
    assert fx.convert_to_pkr(44, "GBP") == pytest.approx(expected)


def test_convert_to_pkr_unknown_currency_raises_clear_error(deterministic_rates):
    with pytest.raises(ValueError, match="XYZ"):
        fx.convert_to_pkr(100, "XYZ")


def test_fallback_used_and_warning_logged_when_live_fetch_fails(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise TimeoutError("network unreachable")

    monkeypatch.setattr(fx, "_fetch_live_rates", boom)

    with caplog.at_level("WARNING", logger="app.core.fx"):
        rates = fx.get_rates()

    assert rates == fx.FALLBACK_RATES
    assert any("falling back" in rec.message.lower() for rec in caplog.records)


def test_fallback_rates_are_cached_so_a_second_call_does_not_refetch(monkeypatch):
    call_count = 0

    def boom(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise TimeoutError("network unreachable")

    monkeypatch.setattr(fx, "_fetch_live_rates", boom)

    fx.get_rates()
    fx.get_rates()

    assert call_count == 1


def test_build_graph_converts_non_pkr_hourly_rate(deterministic_rates):
    process = {
        "process_id": 1,
        "process_task": [
            {
                "task_id": 1,
                "order": 1,
                "task": {
                    "task_name": "Review",
                    "expected_process_time": 60,
                    "expected_rework_time": 0,
                    "expected_waiting_time": 0,
                    "jobTasks": [
                        {
                            "role": "R",
                            "time_allocation_percentage": 100,
                            "job": {"name": "Analyst", "hourlyRate": 33, "currencyType": "USD"},
                        }
                    ],
                },
            }
        ],
        "gateways": [],
    }

    g = build_graph(process)
    raci = g.nodes[1]["raci"]
    assert len(raci) == 1

    converted_rate = raci[0]["hourly_rate"]
    unconverted_rate = 33

    expected = (33 / DETERMINISTIC_RATES["USD"]) * DETERMINISTIC_RATES["PKR"]
    assert converted_rate == pytest.approx(expected)
    assert converted_rate != unconverted_rate
    assert converted_rate > unconverted_rate * 200  # USD->PKR is roughly a ~278x scale-up


def test_build_graph_leaves_pkr_hourly_rate_unchanged(deterministic_rates):
    process = {
        "process_id": 1,
        "process_task": [
            {
                "task_id": 1,
                "order": 1,
                "task": {
                    "task_name": "Approve",
                    "expected_process_time": 60,
                    "expected_rework_time": 0,
                    "expected_waiting_time": 0,
                    "jobTasks": [
                        {
                            "role": "R",
                            "time_allocation_percentage": 100,
                            "job": {"name": "Dean", "hourlyRate": 5000, "currencyType": "PKR"},
                        }
                    ],
                },
            }
        ],
        "gateways": [],
    }

    g = build_graph(process)
    assert g.nodes[1]["raci"][0]["hourly_rate"] == 5000


def test_build_graph_defaults_missing_currency_type_to_pkr_passthrough(deterministic_rates):
    process = {
        "process_id": 1,
        "process_task": [
            {
                "task_id": 1,
                "order": 1,
                "task": {
                    "task_name": "Legacy task",
                    "expected_process_time": 60,
                    "expected_rework_time": 0,
                    "expected_waiting_time": 0,
                    "jobTasks": [
                        {
                            "role": "R",
                            "time_allocation_percentage": 100,
                            "job": {"name": "Agent", "hourlyRate": 20},
                        }
                    ],
                },
            }
        ],
        "gateways": [],
    }

    g = build_graph(process)
    assert g.nodes[1]["raci"][0]["hourly_rate"] == 20


def test_redesign_endpoint_succeeds_end_to_end_when_fx_api_is_unreachable(monkeypatch, as_is_process):
    def boom(*args, **kwargs):
        raise TimeoutError("network unreachable")

    monkeypatch.setattr(fx, "_fetch_live_rates", boom)

    client = TestClient(app)
    files = {"file": ("asIsProcess.json", json.dumps(as_is_process), "application/json")}
    response = client.post("/redesign", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["before"]["cost"] > 0
