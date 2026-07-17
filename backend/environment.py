from __future__ import annotations

from working_process import build_working_process
from serializer import working_process_to_json
from analysis import analyze_process
from reward_function import compute_reward
from state_encoder import encode_state
from heuristics import HEURISTICS

MAX_STEPS = 8


class Environment:
    def __init__(self, process_data: dict, goal):
        self.process_data = process_data
        self.goal = goal
        baseline_wp = build_working_process(process_data)
        baseline_metrics = analyze_process(working_process_to_json(baseline_wp))
        self.baseline_ct = baseline_metrics.cycle_time
        self.baseline_cost = baseline_metrics.resource_cost

    def reset(self):
        self.wp = build_working_process(self.process_data)
        self.used = set()
        metrics = analyze_process(working_process_to_json(self.wp))
        self.ct = metrics.cycle_time
        self.cost = metrics.resource_cost
        return encode_state(self.wp, self.used, self.baseline_ct, self.baseline_cost, self.ct, self.cost)

    def qualifying_heuristics(self):
        result = []
        for h in HEURISTICS:
            if h.NAME in self.used:
                continue
            ok, _, candidates = h.qualify(self.wp)
            if ok:
                result.append((h, candidates))
        return result

    def step(self, heuristic, candidates):
        old_ct, old_cost = self.ct, self.cost
        target = heuristic.select_target(self.wp, candidates)
        heuristic.apply(self.wp, target)
        self.used.add(heuristic.NAME)

        metrics = analyze_process(working_process_to_json(self.wp))
        self.ct, self.cost = metrics.cycle_time, metrics.resource_cost

        reward_info = compute_reward(old_ct, self.ct, old_cost, self.cost, self.goal)
        state = encode_state(self.wp, self.used, self.baseline_ct, self.baseline_cost, self.ct, self.cost)
        done = len(self.qualifying_heuristics()) == 0 or len(self.used) >= MAX_STEPS
        return state, reward_info, done