"""Regression tests for the gateway branch serialization bug and the
zero-valid-actions graceful path.
"""

import json

from fastapi.testclient import TestClient

from app.core import environment as environment_module
from app.core.heuristics import elimination_apply
from app.core.parser import build_graph, validate_process_definition
from app.core.replay import serialize_graph
from app.main import app
from app.services import redesign_service

client = TestClient(app)


def test_elimination_preserves_sibling_branch_to_same_target(as_is_process):
    """Gateway 1470 has Yes->995 (p=0.7) and No->END (p=0.3). Eliminating
    task 995 (whose successor is also END) reroutes the Yes branch to END,
    landing on the same target as the pre-existing No branch. A DiGraph can
    only hold one edge per (source, target) pair, so naively re-adding the
    edge overwrote the sibling branch entirely - this is the bug being
    regression-tested here: both branches must survive with their original
    probabilities.
    """
    validate_process_definition(as_is_process)
    g = build_graph(as_is_process)

    g2 = elimination_apply(g, (995,))
    out = serialize_graph(g2, as_is_process)

    gw1470 = next(gw for gw in out["gateways"] if gw["gateway_pk_id"] == 1470)
    assert len(gw1470["branches"]) == 2

    conditions = {b["condition"]: b["probability"] for b in gw1470["branches"]}
    assert conditions == {"Yes": 0.7, "No": 0.3}


def test_redesign_endpoint_preserves_sibling_branch_when_995_eliminated(as_is_process):
    """End-to-end version of the same regression via the public API: if the
    trained sequence happens to eliminate task 995, gateway 1470 must still
    show both branches in the response.
    """
    files = {"file": ("asIsProcess.json", json.dumps(as_is_process), "application/json")}
    resp = client.post("/redesign", files=files)
    assert resp.status_code == 200
    body = resp.json()

    eliminated_995 = any(
        step["heuristic_id"] == "activity_elimination" and step["target"] == [995]
        for step in body["sequence"]
    )
    if not eliminated_995:
        return  # RL search didn't pick this action this run; graph-level test above covers the bug directly.

    gw1470 = next(gw for gw in body["toBeProcess"]["gateways"] if gw["gateway_pk_id"] == 1470)
    assert len(gw1470["branches"]) == 2
    conditions = {b["condition"]: b["probability"] for b in gw1470["branches"]}
    assert conditions == {"Yes": 0.7, "No": 0.3}


def test_zero_valid_actions_returns_before_equals_after(monkeypatch, as_is_process):
    """If no heuristic has any applicable candidate at all, the pipeline
    must still return 200 with an empty sequence and before == after,
    instead of erroring or hanging.
    """
    monkeypatch.setattr(environment_module, "all_candidates", lambda g: [])

    result = redesign_service.redesign(as_is_process)

    assert result["sequence"] == []
    assert result["before"] == result["after"]
    assert result["improvement"]["cycle_time_percent"] == 0.0
    assert result["improvement"]["cost_percent"] == 0.0


def test_zero_valid_actions_via_api_returns_200(monkeypatch, as_is_process):
    monkeypatch.setattr(environment_module, "all_candidates", lambda g: [])

    files = {"file": ("asIsProcess.json", json.dumps(as_is_process), "application/json")}
    resp = client.post("/redesign", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["sequence"] == []
    assert body["before"] == body["after"]
