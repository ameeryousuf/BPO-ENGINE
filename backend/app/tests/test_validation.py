"""Tests for input validation at the /redesign API boundary.

Each test asserts a 400 response whose detail message names the actual
offending field/task/gateway, not a generic error.
"""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _post(process: dict):
    files = {"file": ("process.json", json.dumps(process), "application/json")}
    return client.post("/redesign", files=files)


def _task(task_id=1, order=1, value_classification="VA", **task_overrides):
    task = {
        "task_code": f"T{task_id}",
        "task_name": f"Task {task_id}",
        "expected_process_time": 60,
        "expected_rework_time": 0,
        "expected_waiting_time": 0,
        "jobTasks": [
            {"role": "R", "time_allocation_percentage": "100", "job": {"name": "Agent", "hourlyRate": 20}}
        ],
    }
    task.update(task_overrides)
    return {"task_id": task_id, "order": order, "value_classification": value_classification, "task": task}


def _valid_process():
    return {
        "process_id": 1,
        "process_name": "Test Process",
        "process_task": [_task(1)],
        "gateways": [],
    }


def _valid_process_with_gateway():
    return {
        "process_id": 1,
        "process_name": "Test Process",
        "process_task": [_task(1, order=1), _task(2, order=2)],
        "gateways": [
            {
                "gateway_pk_id": 101,
                "gateway_type": "EXCLUSIVE",
                "name": "Check",
                "after_task_id": 1,
                "after_gateway_id": None,
                "branches": [
                    {"target_task_id": 2, "target_gateway_id": None, "condition": "Yes", "probability": 0.6},
                    {"target_task_id": None, "target_gateway_id": None, "condition": "No",
                     "connect_to_end": True, "probability": 0.4},
                ],
            }
        ],
    }


# --- 1. process_task missing / empty / not a list -------------------------

def test_rejects_missing_process_task():
    process = _valid_process()
    del process["process_task"]
    resp = _post(process)
    assert resp.status_code == 400
    assert "process_task" in resp.json()["detail"]


def test_rejects_empty_process_task():
    process = _valid_process()
    process["process_task"] = []
    resp = _post(process)
    assert resp.status_code == 400
    assert "process_task" in resp.json()["detail"]


def test_rejects_non_list_process_task():
    process = _valid_process()
    process["process_task"] = "not-a-list"
    resp = _post(process)
    assert resp.status_code == 400
    assert "process_task" in resp.json()["detail"]


# --- 2. dangling gateway references ---------------------------------------

def test_rejects_dangling_branch_target_task_id():
    process = _valid_process_with_gateway()
    process["gateways"][0]["branches"][0]["target_task_id"] = 9999
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "9999" in detail
    assert "101" in detail


def test_rejects_dangling_branch_target_gateway_id():
    process = _valid_process_with_gateway()
    process["gateways"][0]["branches"][0]["target_task_id"] = None
    process["gateways"][0]["branches"][0]["target_gateway_id"] = 8888
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "8888" in detail


def test_rejects_dangling_after_task_id():
    process = _valid_process_with_gateway()
    process["gateways"][0]["after_task_id"] = 7777
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "7777" in detail


# --- 3. gateway branch probabilities must sum to ~1.0 ----------------------

def test_rejects_branch_probabilities_not_summing_to_one():
    process = _valid_process_with_gateway()
    process["gateways"][0]["branches"][0]["probability"] = 0.6
    process["gateways"][0]["branches"][1]["probability"] = 0.1
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "101" in detail
    assert "probabilit" in detail.lower()


def test_accepts_branch_probabilities_within_tolerance():
    process = _valid_process_with_gateway()
    process["gateways"][0]["branches"][0]["probability"] = 0.605
    process["gateways"][0]["branches"][1]["probability"] = 0.4
    resp = _post(process)
    assert resp.status_code == 200


# --- 4. duplicate task_id ---------------------------------------------------

def test_rejects_duplicate_task_id():
    process = _valid_process()
    process["process_task"].append(_task(1, order=2))
    resp = _post(process)
    assert resp.status_code == 400
    assert "1" in resp.json()["detail"]
    assert "uplicate" in resp.json()["detail"]


# --- 5. numeric coercion for pct / hourlyRate -------------------------------

def test_rejects_non_numeric_time_allocation_percentage():
    process = _valid_process()
    process["process_task"][0]["task"]["jobTasks"][0]["time_allocation_percentage"] = "not-a-number"
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "time_allocation_percentage" in detail
    assert "1" in detail


def test_rejects_non_numeric_hourly_rate():
    process = _valid_process()
    process["process_task"][0]["task"]["jobTasks"][0]["job"]["hourlyRate"] = "not-a-number"
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "hourlyRate" in detail
    assert "1" in detail


def test_accepts_numeric_strings_for_pct_and_hourly_rate():
    process = _valid_process()
    process["process_task"][0]["task"]["jobTasks"][0]["time_allocation_percentage"] = "100"
    process["process_task"][0]["task"]["jobTasks"][0]["job"]["hourlyRate"] = "20"
    resp = _post(process)
    assert resp.status_code == 200


# --- 6. negative time fields -------------------------------------------------

def test_rejects_negative_expected_process_time():
    process = _valid_process()
    process["process_task"][0]["task"]["expected_process_time"] = -10
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "expected_process_time" in detail
    assert "negative" in detail


def test_rejects_negative_expected_rework_time():
    process = _valid_process()
    process["process_task"][0]["task"]["expected_rework_time"] = -5
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "expected_rework_time" in detail
    assert "negative" in detail


def test_rejects_negative_expected_waiting_time():
    process = _valid_process()
    process["process_task"][0]["task"]["expected_waiting_time"] = -1
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "expected_waiting_time" in detail
    assert "negative" in detail


# --- 7. orphaned nodes: unreachable from START or cannot reach END --------

def test_rejects_gateway_island_unreachable_from_start():
    process = _valid_process()
    process["gateways"] = [
        {
            "gateway_pk_id": 501,
            "gateway_type": "EXCLUSIVE",
            "name": "IslandA",
            "after_task_id": None,
            "after_gateway_id": 502,
            "branches": [],
        },
        {
            "gateway_pk_id": 502,
            "gateway_type": "EXCLUSIVE",
            "name": "IslandB",
            "after_task_id": None,
            "after_gateway_id": 501,
            "branches": [],
        },
    ]
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "unreachable" in detail.lower() or "cannot reach" in detail.lower()
    assert "501" in detail or "502" in detail


# --- input size cap ---------------------------------------------------------

def test_rejects_process_task_list_over_max_size():
    process = _valid_process()
    process["process_task"] = [_task(i, order=i) for i in range(1, 202)]
    resp = _post(process)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "200" in detail


# --- sanity: the baseline valid fixtures used above actually succeed -------

def test_valid_process_is_accepted():
    resp = _post(_valid_process())
    assert resp.status_code == 200


def test_valid_process_with_gateway_is_accepted():
    resp = _post(_valid_process_with_gateway())
    assert resp.status_code == 200
