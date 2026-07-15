"""Shared pytest fixtures pointing at the sample process JSON files."""

import json
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent.parent / "data"
AS_IS_PROCESS_PATH = DATA_DIR / "asIsProcess.json"
SECOND_PROCESS_PATH = DATA_DIR / "secondProcess.json"


def load_fixture(path: Path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


@pytest.fixture
def as_is_process() -> dict:
    return load_fixture(AS_IS_PROCESS_PATH)


@pytest.fixture
def second_process() -> dict:
    return load_fixture(SECOND_PROCESS_PATH)
