# BPO Redesign Engine

A FastAPI service that redesigns a business process. Upload a BPMN process
JSON file and get back the redesigned process, before/after metrics, and
the sequence of redesign heuristics applied.

## Setup

```
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```
uvicorn app.main:app --reload
```

## Usage

Upload a process JSON file to `POST /redesign`:

```
curl -X POST http://127.0.0.1:8000/redesign \
  -F "file=@app/data/asIsProcess.json"
```

Response:

```json
{
  "before": { "cycle_time_minutes": 0, "cost": 0 },
  "after": { "cycle_time_minutes": 0, "cost": 0 },
  "improvement": { "cycle_time_percent": 0, "cost_percent": 0 },
  "sequence": [
    { "heuristic_id": "...", "target": [], "description": "..." }
  ],
  "toBeProcess": { }
}
```

## Tests

```
pytest app/tests
```

## Project layout

```
app/
  main.py               FastAPI app
  api/                  HTTP layer (request/response, status codes)
  services/              Orchestrates the redesign pipeline
  core/                  Parsing, metrics, heuristics, RL environment/trainer, replay
  models/                Pydantic response models
  exceptions.py          Domain-level exceptions
  logging_config.py      Logging setup
  data/                  Sample process JSON files used by tests
  tests/                 Test suite
```
