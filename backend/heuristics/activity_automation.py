NAME = "Activity Automation"
TIME_FACTOR = 0.5
WAIT_FACTOR = 0.5


def qualify(wp):
    candidates = [nid for nid, t in wp.tasks.items() if float(t.get("expected_process_time") or 0) > 0]
    if not candidates:
        return False, "Every task already has no processing time left to automate.", []
    return True, None, candidates


def select_target(wp, candidates):
    return max(candidates, key=lambda nid: float(wp.tasks[nid].get("expected_process_time") or 0))


def apply(wp, target):
    task = wp.tasks[target]
    task["expected_process_time"] = float(task.get("expected_process_time") or 0) * TIME_FACTOR
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * WAIT_FACTOR
    return [target.replace("Activity_", "")]