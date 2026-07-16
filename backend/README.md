# BPO Redesign Engine

A FastAPI service that redesigns a business process. Upload a BPMN process
JSON file and get back the redesigned process, a before/after Chapter 7
quantitative-analysis report (flow analysis, Cycle Time Efficiency, cost,
resource utilization, Little's Law/avg WIP, bottleneck detection), and the
sequence of redesign heuristics applied.

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

Response - `before`/`after` carry the full Chapter 7 quantitative-analysis
suite (see [`QUANTITATIVE_ANALYSIS.md`](QUANTITATIVE_ANALYSIS.md) for what
each field means and the assumptions behind it):

```json
{
  "before": {
    "cycle_time_minutes": 1169.48,
    "cost": 190180.4,
    "cycle_time_efficiency_percent": 28.17,
    "value_add_minutes": 329.4,
    "non_value_add_minutes": 840.08,
    "avg_wip": 0.116,
    "resource_utilization": [
      {
        "job_id": 651,
        "job_name": "Curriculum & Proposal Officer",
        "required_minutes_per_week": 607.96,
        "available_minutes_per_week": 2400.0,
        "utilization_percent": 25.33
      }
    ],
    "bottleneck": { "job_id": 651, "job_name": "Curriculum & Proposal Officer", "utilization_percent": 25.33 }
  },
  "after": { "...": "same shape as before" },
  "improvement": {
    "cycle_time_percent": 36.88,
    "cost_percent": 28.82,
    "cte_percent_change": 16.86,
    "avg_wip_percent_change": 36.9,
    "bottleneck_shifted": false
  },
  "sequence": [
    { "heuristic_id": "...", "target": [], "description": "..." }
  ],
  "toBeProcess": { }
}
```

`before.cost`/`after.cost` is the currency-normalized figure (PKR), the
same meaning this field has always had since the FX fix
(`../KNOWN_LIMITATIONS.md`) - not the raw/uncorrected figure
`quantitative_analysis.compare()` reports under the same key name for its
own, separate contract (kept there only to match historically validated
thesis numbers). `utilization_percent` is `null` for a resource with no
recorded capacity (missing `hours_per_day`/`days_per_week`) rather than
`Infinity`, which isn't valid JSON.

## Tests

```
pytest app/tests
```

## Quantitative process analysis (Chapter 7 toolkit)

`app/core/quantitative_analysis.py` implements the Dumas et al. Chapter 7
toolkit (Flow Analysis/Cycle Time Law, Cycle Time Efficiency,
Activity-Based Costing, resource utilization & Little's Law) on top of the
same graph representation, and produces a before/after report comparing an
as-is process against the to-be process this repo's RL redesign engine
generates from it:

```
python report.py app/data/asIsProcess.json --out-dir out
```

writes `out/PROC-APEL-001_analysis.json` (contract-shaped) and
`out/PROC-APEL-001_report.md` (human-readable). See
[`QUANTITATIVE_ANALYSIS.md`](QUANTITATIVE_ANALYSIS.md) for the assumptions
behind the numbers (rework-loop handling, FX rates, instance-frequency
derivation, why the `cost` field stays raw/uncorrected for backward
compatibility while `cost_currency_normalized` is the corrected figure).

## Project layout

```
app/
  main.py               FastAPI app
  api/                  HTTP layer (request/response, status codes)
  services/              Orchestrates the redesign pipeline
  core/                  Parsing, metrics, heuristics, RL environment/trainer, replay,
                         quantitative_analysis (Chapter 7 toolkit + compare())
  models/                Pydantic response models
  exceptions.py          Domain-level exceptions
  logging_config.py      Logging setup
  data/                  Sample process JSON files used by tests
  tests/                 Test suite
report.py                CLI: as-is JSON -> before/after analysis report (JSON + Markdown)
QUANTITATIVE_ANALYSIS.md Assumptions behind the quantitative-analysis numbers
```
