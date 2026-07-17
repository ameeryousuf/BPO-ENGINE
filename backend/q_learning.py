from __future__ import annotations

import random
from collections import defaultdict

from environment import Environment


def train_q_table(process_data, goal, episodes=300, alpha=0.3, gamma=0.9,
                   epsilon_start=1.0, epsilon_min=0.05, epsilon_decay=0.97):
    env = Environment(process_data, goal)
    Q = defaultdict(float)
    epsilon = epsilon_start

    for _ in range(episodes):
        state = env.reset()
        done = False
        while not done:
            qualifying = env.qualifying_heuristics()
            if not qualifying:
                break

            if random.random() < epsilon:
                heuristic, candidates = random.choice(qualifying)
            else:
                heuristic, candidates = max(qualifying, key=lambda hc: Q[(state, hc[0].NAME)])

            new_state, reward_info, done = env.step(heuristic, candidates)
            reward = reward_info["reward"]

            future_qualifying = env.qualifying_heuristics()
            max_future_q = max([Q[(new_state, h.NAME)] for h, _ in future_qualifying], default=0.0)

            key = (state, heuristic.NAME)
            Q[key] += alpha * (reward + gamma * max_future_q - Q[key])

            state = new_state

        epsilon = max(epsilon_min, epsilon * epsilon_decay)

    return Q