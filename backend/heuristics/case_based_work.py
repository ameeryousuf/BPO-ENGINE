from .config import WAIT_TO_PROCESS_RATIO, target_rule_results, existential_rule_results
from . import trusted_party

NAME = "Case-Based Work"
BATCH_PERIODS = {"WEEK", "MONTH"}


def _waits_much_longer_than_processing(task):
    waiting = float(task.get("expected_waiting_time") or 0)
    processing = float(task.get("expected_process_time") or 0)
    return processing > 0 and waiting > WAIT_TO_PROCESS_RATIO * processing


def _on_batch_schedule(task):
    return task.get("frequency_period") in BATCH_PERIODS


def qualify(wp):
    tp_ok, _, tp_candidates = trusted_party.qualify(wp)
    tp_set = set(tp_candidates) if tp_ok else set()

    candidates = []
    for nid, task in wp.tasks.items():
        if not _waits_much_longer_than_processing(task):
            continue
        if not _on_batch_schedule(task):
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


def rule_checks(wp, target=None):
    tp_ok, _, tp_candidates = trusted_party.qualify(wp)
    tp_set = set(tp_candidates) if tp_ok else set()

    rule_fns = [
        ("Waiting time far exceeds processing time", lambda nid: _waits_much_longer_than_processing(wp.tasks[nid])),
        ("Runs on a weekly or monthly schedule", lambda nid: _on_batch_schedule(wp.tasks[nid])),
        ("Not already claimed by Trusted Party", lambda nid: nid not in tp_set),
    ]
    if target is not None:
        return target_rule_results(rule_fns, target[0] if isinstance(target, list) else target)
    return existential_rule_results(rule_fns, list(wp.tasks.keys()))