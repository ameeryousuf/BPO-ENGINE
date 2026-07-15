"""Tabular Q-learning trainer that searches for a good heuristic sequence."""

import logging
import random
from collections import defaultdict
from typing import Optional, Tuple

import networkx as nx

from app.core.environment import ProcessRedesignEnv

logger = logging.getLogger(__name__)

ALPHA = 0.1
GAMMA = 0.9
EPISODES = 2000
EPSILON_START = 1.0
EPSILON_END = 0.05
EPSILON_DECAY = 0.999


def train(baseline_graph: nx.DiGraph, baseline_metrics: dict) -> Tuple[dict, Optional[list], Optional[dict], dict]:
    """Train a Q-learning agent over the redesign heuristic search space.

    Returns ``(Q, best_sequence, best_final_metrics, baseline_metrics)``
    where ``best_sequence`` is the list of (heuristic_id, target) actions
    from the highest-total-reward episode.
    """
    env = ProcessRedesignEnv(baseline_graph, baseline_metrics)
    Q = defaultdict(float)
    epsilon = EPSILON_START

    best_reward_total = float("-inf")
    best_sequence = None
    best_final_metrics = None

    for ep in range(EPISODES):
        state = env.reset()
        done = False
        episode_actions = []
        episode_reward_total = 0.0

        while not done:
            actions = env.valid_actions()
            if not actions:
                break

            if random.random() < epsilon:
                action = random.choice(actions)
            else:
                q_values = [Q[(state, a)] for a in actions]
                max_q = max(q_values)
                best_actions = [a for a, q in zip(actions, q_values) if q == max_q]
                action = random.choice(best_actions)

            next_state, reward, done, info = env.step(action)
            episode_actions.append(action)
            episode_reward_total += reward

            next_actions = env.valid_actions()
            future_q = max([Q[(next_state, a)] for a in next_actions], default=0.0)
            Q[(state, action)] += ALPHA * (reward + GAMMA * future_q - Q[(state, action)])

            state = next_state

        if episode_reward_total > best_reward_total:
            best_reward_total = episode_reward_total
            best_sequence = episode_actions
            best_final_metrics = env.current_metrics

        epsilon = max(EPSILON_END, epsilon * EPSILON_DECAY)

    logger.info(
        "Training complete: %d episodes, best_reward_total=%.4f, best_final_metrics=%s",
        EPISODES, best_reward_total, best_final_metrics,
    )
    return Q, best_sequence, best_final_metrics, baseline_metrics
