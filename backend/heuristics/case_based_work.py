from .config import WAIT_TO_PROCESS_RATIO
from . import trusted_party

NAME = "Case-Based Work"
BATCH_PERIODS = {"WEEK", "MONTH"}


def qualify(wp):
    tp_ok, _, tp_candidates = trusted_party.qualify(wp)
    tp_set = set(tp_candidates) if tp_ok else set()

    candidates = []
    for nid, task in wp.tasks.items():
        waiting = float(task.get("expected_waiting_time") or 0)
        processing = float(task.get("expected_process_time") or 0)
        if processing <= 0 or waiting <= WAIT_TO_PROCESS_RATIO * processing:
            continue
        if task.get("frequency_period") not in BATCH_PERIODS:
            continue
        if nid in tp_set:
            continue
        candidates.append(nid)

    if not candidates:
        return False, "No step is both waiting far longer than the work itself takes and running on a fixed batch schedule.", []
    return True, None, candidates


def select_target(wp, candidates):
    return max(candidates, key=lambda nid: float(wp.tasks[nid].get("expected_waiting_time") or 0))


def apply(wp, target):
    task = wp.tasks[target]
    task["expected_waiting_time"] = 0.0
    task["frequency_period"] = "EVENT"
    return [target.replace("Activity_", "")]