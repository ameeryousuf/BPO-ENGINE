"""Tests for the POST /redesign API endpoint."""

import json

from fastapi.testclient import TestClient

from app.main import app
from app.tests.conftest import AS_IS_PROCESS_PATH, SECOND_PROCESS_PATH

client = TestClient(app)

EXPECTED_RESPONSE_KEYS = {"before", "after", "improvement", "sequence", "toBeProcess"}


def test_health_check():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "running"}


def test_redesign_endpoint_returns_redesigned_process(as_is_process):
    files = {"file": ("asIsProcess.json", json.dumps(as_is_process), "application/json")}
    response = client.post("/redesign", files=files)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == EXPECTED_RESPONSE_KEYS


def test_redesign_endpoint_accepts_real_file_upload_from_disk():
    """Regression test: reproduces `curl -F "file=@path"` by uploading the raw
    bytes of a file straight off disk, the same way Postman/curl send a real
    multipart file part. Catches endpoints that mistakenly expect a filesystem
    path string instead of `UploadFile`/`File(...)`.
    """
    with open(AS_IS_PROCESS_PATH, "rb") as f:
        files = {"file": ("asIsProcess.json", f, "application/json")}
        response = client.post("/redesign", files=files)

    assert response.status_code == 200
    assert set(response.json().keys()) == EXPECTED_RESPONSE_KEYS


def test_redesign_endpoint_accepts_second_process_file_upload_from_disk():
    with open(SECOND_PROCESS_PATH, "rb") as f:
        files = {"file": ("secondProcess.json", f, "application/json")}
        response = client.post("/redesign", files=files)

    assert response.status_code == 200
    assert set(response.json().keys()) == EXPECTED_RESPONSE_KEYS


def test_redesign_endpoint_rejects_invalid_json():
    files = {"file": ("bad.json", "{not valid json", "application/json")}
    response = client.post("/redesign", files=files)
    assert response.status_code == 400


def test_redesign_endpoint_rejects_invalid_process_definition():
    files = {"file": ("bad.json", json.dumps({"foo": "bar"}), "application/json")}
    response = client.post("/redesign", files=files)
    assert response.status_code == 422
