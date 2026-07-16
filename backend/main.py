import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException

from validation import validate_process
from analysis import analyze_process
from critical_path import find_critical_paths

BASE_DIR = Path(__file__).parent
PROCESS_DIR = BASE_DIR / "processes"

app = FastAPI()


def load_process(process_id: str) -> dict:
    path = PROCESS_DIR / f"{process_id}.json"

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Process {process_id} not found.",
        )

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail=f"Process {process_id} contains invalid JSON.",
        )


@app.post("/process/{process_id}")
def validate(process_id: str):
    process = load_process(process_id)
    report = validate_process(process)

    if not report.is_valid:
        return {
            "success": False,
            "message": "Validation error",
            "process_id": report.process_id,
            "process_name": report.process_name,
            "issues": [issue.message for issue in report.issues],
        }

    analysis = analyze_process(process)
    critical_paths = find_critical_paths(process)

    return {
        "success": True,
        "message": "Process analyzed successfully",
        "process_name": report.process_name,
        "process_id": report.process_id,
        "analysis": {
            "cycle_time": analysis.cycle_time,
            "theoretical_cycle_time": analysis.theoretical_cycle_time,
            "cycle_time_efficiency": analysis.cycle_time_efficiency,
            "resource_cost": analysis.resource_cost,
            "raci_cost": analysis.raci_cost,
            "time_unit": analysis.time_unit,
            "cost_unit": analysis.cost_unit,
        },
        "critical_paths": critical_paths,
    }

    


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)