import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from validation import validate_process
from analysis import analyze_process
from critical_path import find_critical_paths
from redesign import redesign_process

BASE_DIR = Path(__file__).parent
PROCESS_DIR = BASE_DIR / "processes"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_process(process_id: str) -> dict:
    path = PROCESS_DIR / f"{process_id}.json"

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Process {process_id} not found.")

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Process {process_id} contains invalid JSON.")


@app.post("/process/{process_id}")
def analyze(process_id: str, goal: str = "both", episodes: int = 300, redesign: bool = True):
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

    analysis_result = analyze_process(process)
    critical_paths = find_critical_paths(process)

    response = {
        "success": True,
        "message": "Process analyzed successfully",
        "process_id": report.process_id,
        "process_name": report.process_name,
        "analysis": {
            "cycle_time": analysis_result.cycle_time,
            "theoretical_cycle_time": analysis_result.theoretical_cycle_time,
            "cycle_time_efficiency": analysis_result.cycle_time_efficiency,
            "resource_cost": analysis_result.resource_cost,
            "raci_cost": analysis_result.raci_cost,
            "time_unit": analysis_result.time_unit,
            "cost_unit": analysis_result.cost_unit,
        },
        "critical_paths": critical_paths,
    }

    if not redesign:
        return response

    try:
        redesign_result = redesign_process(process, goal, episodes=episodes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    response["message"] = "Process analyzed and redesigned successfully"
    response["goal"] = redesign_result["goal"]
    response["to_be"] = redesign_result["to_be"]
    response["overall_improvement"] = redesign_result["overall_improvement"]
    response["redesign_trace"] = redesign_result["redesign_trace"]
    response["stop_reason"] = redesign_result["stop_reason"]
    response["final_bpmn_xml"] = redesign_result["final_bpmn_xml"]

    return response


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)