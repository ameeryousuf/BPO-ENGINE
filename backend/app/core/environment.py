"""Reinforcement-learning environment over the redesign heuristic search space.

An episode starts from the process baseline and applies at most
``MAX_STEPS`` heuristics, one per step, without repeating an action. The
state is a coarse discretization of cumulative cycle-time/cost improvement
so that a tabular Q-learning agent (see ``app.core.trainer``) can learn
over it.
"""

import copy
from typing import Tuple

import networkx as nx

from app.core.heuristics import HEURISTICS, all_candidates
from app.core.metrics import compute_metrics

MAX_STEPS = 6
N_BUCKETS = 10


def _bucket(improvement_pct: float) -> int:
    b = int(improvement_pct * N_BUCKETS)
    return max(0, min(N_BUCKETS - 1, b))


class ProcessRedesignEnv:
    """RL environment wrapping a baseline process graph.

    Takes an already-parsed baseline graph and its metrics so that parsing
    happens exactly once per redesign request, upstream in the service
    layer, rather than being re-derived from a file path.
    """

    def __init__(self, baseline_graph: nx.DiGraph, baseline_metrics: dict):
        self.baseline_graph = baseline_graph
        self.baseline_metrics = baseline_metrics
        self.reset()

    def reset(self) -> Tuple[int, int, int]:
        self.graph = copy.deepcopy(self.baseline_graph)
        self.step_count = 0
        self.used_actions = set()
        self.current_metrics = dict(self.baseline_metrics)
        return self._state()

    def _state(self) -> Tuple[int, int, int]:
        ct0 = self.baseline_metrics["cycle_time_minutes"]
        c0 = self.baseline_metrics["cost"]
        ct_improve = max(0.0, (ct0 - self.current_metrics["cycle_time_minutes"]) / ct0)
        c_improve = max(0.0, (c0 - self.current_metrics["cost"]) / c0)
        return (self.step_count, _bucket(ct_improve), _bucket(c_improve))

    def valid_actions(self) -> list:
        actions = []
        for hid, target in all_candidates(self.graph):
            sig = (hid, target)
            if sig not in self.used_actions:
                actions.append(sig)
        return actions

    def step(self, action: tuple):
        hid, target = action
        _, apply_fn = HEURISTICS[hid]

        old_metrics = self.current_metrics
        new_graph = apply_fn(self.graph, target)

        if not nx.is_directed_acyclic_graph(new_graph):
            self.used_actions.add(action)
            self.step_count += 1
            done = self.step_count >= MAX_STEPS or len(self.valid_actions()) == 0
            return self._state(), -1.0, done, {"metrics": old_metrics, "invalid_cycle": True}

        new_metrics = compute_metrics(new_graph)

        ct0 = self.baseline_metrics["cycle_time_minutes"]
        c0 = self.baseline_metrics["cost"]
        reward = (
            (old_metrics["cycle_time_minutes"] - new_metrics["cycle_time_minutes"]) / ct0
            + (old_metrics["cost"] - new_metrics["cost"]) / c0
        )

        self.graph = new_graph
        self.current_metrics = new_metrics
        self.used_actions.add(action)
        self.step_count += 1

        done = self.step_count >= MAX_STEPS or len(self.valid_actions()) == 0
        return self._state(), reward, done, {"metrics": new_metrics}
