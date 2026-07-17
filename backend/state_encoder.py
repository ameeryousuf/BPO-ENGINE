from __future__ import annotations

from heuristics import HEURISTICS

NUM_BANDS = 5


def _band(current, baseline):
    if baseline <= 0:
        return 0
    ratio = max(0.0, min(1.0, current / baseline))
    band = int((1 - ratio) * NUM_BANDS)
    return min(band, NUM_BANDS - 1)


def encode_state(wp, used, baseline_ct, baseline_cost, current_ct, current_cost):
    time_band = _band(current_ct, baseline_ct)
    cost_band = _band(current_cost, baseline_cost)
    flags = []
    for h in HEURISTICS:
        if h.NAME in used:
            flags.append(0)
            continue
        ok, _, _ = h.qualify(wp)
        flags.append(1 if ok else 0)
    return (time_band, cost_band, tuple(flags))