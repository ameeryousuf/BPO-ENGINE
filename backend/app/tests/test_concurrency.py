"""Concurrency and runtime-safety tests.

Verifies that two /redesign requests for different processes, fired at the
same time, never leak state into each other's result, and that a training
run which exceeds the time budget fails fast with a clear error instead of
hanging.
"""

import json
import threading

from fastapi.testclient import TestClient

from app.api import redesign as redesign_module
from app.main import app

client = TestClient(app)


def test_concurrent_redesign_requests_do_not_leak_state(as_is_process, second_process):
    """Fire two /redesign requests concurrently with different input
    processes and assert neither response's content leaked into the
    other's - a regression guard for shared mutable state (e.g. a module-
    level RNG or graph) between requests.
    """
    responses = {}
    errors = {}

    def run(key, process):
        try:
            files = {"file": ("process.json", json.dumps(process), "application/json")}
            responses[key] = client.post("/redesign", files=files)
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
            errors[key] = exc

    t_a = threading.Thread(target=run, args=("a", as_is_process))
    t_b = threading.Thread(target=run, args=("b", second_process))
    t_a.start()
    t_b.start()
    t_a.join(timeout=120)
    t_b.join(timeout=120)

    assert not errors, f"request thread(s) raised: {errors}"
    assert "a" in responses and "b" in responses

    resp_a, resp_b = responses["a"], responses["b"]
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200

    body_a, body_b = resp_a.json(), resp_b.json()

    assert body_a["toBeProcess"]["process_id"] == as_is_process["process_id"]
    assert body_b["toBeProcess"]["process_id"] == second_process["process_id"]

    orig_a_task_ids = {pt["task_id"] for pt in as_is_process["process_task"]}
    orig_b_task_ids = {pt["task_id"] for pt in second_process["process_task"]}
    out_a_task_ids = {pt["task_id"] for pt in body_a["toBeProcess"]["process_task"]}
    out_b_task_ids = {pt["task_id"] for pt in body_b["toBeProcess"]["process_task"]}

    # Every task in each output must come from that same request's input -
    # if state leaked between threads, a task_id from the other process
    # would show up here.
    assert out_a_task_ids <= orig_a_task_ids
    assert out_b_task_ids <= orig_b_task_ids
    assert out_a_task_ids.isdisjoint(orig_b_task_ids)
    assert out_b_task_ids.isdisjoint(orig_a_task_ids)


def test_training_timeout_returns_500_with_clear_message(monkeypatch, as_is_process):
    """A training run that overruns the time budget must fail fast with a
    named 500 error rather than hang the request indefinitely. Uses a tiny
    timeout and a deliberately slow stand-in for the pipeline so the test
    itself stays fast.
    """
    import time

    def _slow_redesign(process_data):
        time.sleep(2)
        return {"before": {}, "after": {}, "improvement": {}, "sequence": [], "toBeProcess": {}}

    monkeypatch.setattr(redesign_module.redesign_service, "redesign", _slow_redesign)
    monkeypatch.setattr(redesign_module, "TRAINING_TIMEOUT_SECONDS", 0.2)

    files = {"file": ("process.json", json.dumps(as_is_process), "application/json")}
    resp = client.post("/redesign", files=files)

    assert resp.status_code == 500
    assert "time limit" in resp.json()["detail"].lower()
