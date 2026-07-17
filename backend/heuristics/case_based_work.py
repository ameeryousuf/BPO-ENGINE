NAME = "Case-Based Work"
BATCH_PERIODS = {"WEEK", "MONTH"}
WAIT_REDUCTION_FACTOR = 0.2


def qualify(wp):
    candidates = [
        nid for nid, t in wp.tasks.items()
        if float(t.get("expected_waiting_time") or 0) > 0
        and t.get("frequency_period") in BATCH_PERIODS
    ]
    if not candidates:
        return False, "No step is being slowed down by waiting for a periodic batch run.", []
    return True, None, candidates


def select_target(wp, candidates):
    return max(candidates, key=lambda nid: float(wp.tasks[nid].get("expected_waiting_time") or 0))


def apply(wp, target):
    task = wp.tasks[target]
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * WAIT_REDUCTION_FACTOR
    return [target.replace("Activity_", "")]