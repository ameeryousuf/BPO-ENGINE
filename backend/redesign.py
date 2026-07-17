from __future__ import annotations

from working_process import build_working_process
from serializer import working_process_to_json
from analysis import analyze_process
from critical_path import find_critical_paths
from reward_function import compute_reward, resolve_goal
from state_encoder import encode_state
from heuristics import HEURISTICS
from q_learning import train_q_table

MAX_STEPS = 8


def _metrics_dict(process_json):
    analysis = analyze_process(process_json)
    critical_paths = find_critical_paths(process_json)
    tasks = [
        {"task_id": pt["task_id"], "task_name": pt["task"].get("task_name", "")}
        for pt in process_json.get("process_task", [])
    ]
    return {
        "cycle_time": analysis.cycle_time,
        "theoretical_cycle_time": analysis.theoretical_cycle_time,
        "cycle_time_efficiency": analysis.cycle_time_efficiency,
        "resource_cost": analysis.resource_cost,
        "raci_cost": analysis.raci_cost,
        "time_unit": analysis.time_unit,
        "cost_unit": analysis.cost_unit,
        "critical_paths": critical_paths,
        "tasks": tasks,
    }, analysis


def redesign_process(process_data: dict, goal_param: str, episodes: int = 300) -> dict:
    goal = resolve_goal(goal_param)

    as_is_json = working_process_to_json(build_working_process(process_data))
    as_is_metrics, as_is_analysis = _metrics_dict(as_is_json)

    Q = train_q_table(process_data, goal, episodes=episodes)

    wp = build_working_process(process_data)
    used = set()
    trace_by_name = {}
    baseline_ct = as_is_analysis.cycle_time
    baseline_cost = as_is_analysis.resource_cost
    current_ct = baseline_ct
    current_cost = baseline_cost

    stop_reason = "max_steps_reached"

    for _ in range(MAX_STEPS):
        qualifying = []
        for h in HEURISTICS:
            if h.NAME in used:
                continue
            ok, reason, candidates = h.qualify(wp)
            if ok:
                qualifying.append((h, candidates))
            else:
                trace_by_name[h.NAME] = {"heuristic": h.NAME, "implemented": False, "reason": reason}

        if not qualifying:
            stop_reason = "no_qualifying_heuristics"
            break

        state = encode_state(wp, used, baseline_ct, baseline_cost, current_ct, current_cost)
        best_heuristic, best_candidates = max(qualifying, key=lambda hc: Q[(state, hc[0].NAME)])
        best_q = Q[(state, best_heuristic.NAME)]

        if best_q <= 0 and any(v > 0 for v in Q.values()):
            stop_reason = "non_positive_q_value"
            for h, _ in qualifying:
                trace_by_name[h.NAME] = {
                    "heuristic": h.NAME,
                    "implemented": False,
                    "reason": "This change was considered, but it was not expected to help enough to be worth applying.",
                }
            break

        target = best_heuristic.select_target(wp, best_candidates)
        before = {"cycle_time": current_ct, "resource_cost": current_cost}
        affected = best_heuristic.apply(wp, target)
        used.add(best_heuristic.NAME)

        step_analysis = analyze_process(working_process_to_json(wp))
        current_ct, current_cost = step_analysis.cycle_time, step_analysis.resource_cost

        reward_info = compute_reward(before["cycle_time"], current_ct, before["resource_cost"], current_cost, goal)

        trace_by_name[best_heuristic.NAME] = {
            "heuristic": best_heuristic.NAME,
            "implemented": True,
            "target_task_ids": affected,
            "before": before,
            "after": {"cycle_time": current_ct, "resource_cost": current_cost},
            "reward": reward_info,
        }
    else:
        stop_reason = "max_steps_reached"

    for h in HEURISTICS:
        if h.NAME not in trace_by_name:
            ok, reason, _ = h.qualify(wp)
            if ok:
                trace_by_name[h.NAME] = {
                    "heuristic": h.NAME,
                    "implemented": False,
                    "reason": "This could have helped, but the redesign process stopped before reaching it.",
                }
            else:
                trace_by_name[h.NAME] = {"heuristic": h.NAME, "implemented": False, "reason": reason}

    redesign_trace = [trace_by_name[h.NAME] for h in HEURISTICS]

    final_json = working_process_to_json(wp)
    to_be_metrics, to_be_analysis = _metrics_dict(final_json)

    overall = compute_reward(
        as_is_analysis.cycle_time, to_be_analysis.cycle_time,
        as_is_analysis.resource_cost, to_be_analysis.resource_cost,
        goal,
    )

    return {
        "success": True,
        "message": "Process redesigned successfully",
        "process_id": process_data.get("process_id"),
        "process_name": process_data.get("process_name", ""),
        "goal": goal.value,
        "as_is": as_is_metrics,
        "to_be": to_be_metrics,
        "overall_improvement": {
            "time_improvement_pct": overall["time_improvement_pct"],
            "cost_improvement_pct": overall["cost_improvement_pct"],
            "total_reward": overall["reward"],
        },
        "redesign_trace": redesign_trace,
        "stop_reason": stop_reason,
        "final_bpmn_xml": final_json["bpmn_xml"],
    }