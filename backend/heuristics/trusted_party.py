NAME = "Trusted Party"
WAIT_THRESHOLD_MINUTES = 1440
WAIT_REDUCTION_FACTOR = 0.1
TIME_REDUCTION_FACTOR = 0.7


def qualify(wp):
    candidates = [
        nid for nid, t in wp.tasks.items()
        if float(t.get("expected_waiting_time") or 0) >= WAIT_THRESHOLD_MINUTES
    ]
    if not candidates:
        return False, "No step depends on waiting for a lengthy outside approval that could be replaced by trusting an existing certificate.", []
    return True, None, candidates


def select_target(wp, candidates):
    return max(candidates, key=lambda nid: float(wp.tasks[nid].get("expected_waiting_time") or 0))


def apply(wp, target):
    task = wp.tasks[target]
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * WAIT_REDUCTION_FACTOR
    task["expected_process_time"] = float(task.get("expected_process_time") or 0) * TIME_REDUCTION_FACTOR
    return [target.replace("Activity_", "")]