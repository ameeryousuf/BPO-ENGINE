from __future__ import annotations

from enum import Enum


class Goal(str, Enum):
    TIME = "time"
    COST = "cost"
    BOTH = "both"


GOAL_WEIGHTS = {
    Goal.TIME: {"time": 1.0, "cost": 0.0},
    Goal.COST: {"time": 0.0, "cost": 1.0},
    Goal.BOTH: {"time": 0.5, "cost": 0.5},
}


def resolve_goal(goal: str) -> Goal:
    try:
        return Goal(goal.lower())
    except ValueError:
        raise ValueError(f"invalid goal '{goal}', expected one of: time, cost, both")


def compute_reward(old_ct: float, new_ct: float, old_cost: float, new_cost: float, goal: Goal) -> dict:
    weights = GOAL_WEIGHTS[goal]

    time_improvement = (old_ct - new_ct) / old_ct if old_ct > 0 else 0.0
    cost_improvement = (old_cost - new_cost) / old_cost if old_cost > 0 else 0.0

    reward = weights["time"] * time_improvement + weights["cost"] * cost_improvement

    return {
        "goal": goal.value,
        "time_improvement_pct": round(time_improvement * 100, 4),
        "cost_improvement_pct": round(cost_improvement * 100, 4),
        "reward": round(reward, 6),
    }