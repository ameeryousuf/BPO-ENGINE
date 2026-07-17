NAME = "Empower"
WAIT_REDUCTION_FACTOR = 0.8


def _accountable_entries(task):
    return [jt for jt in (task.get("jobTasks") or []) if jt.get("role") == "A"]


def qualify(wp):
    candidates = [nid for nid, t in wp.tasks.items() if _accountable_entries(t)]
    if not candidates:
        return False, "There is no extra sign-off step left that could be skipped.", []
    return True, None, candidates


def select_target(wp, candidates):
    def cost_of_a_role(nid):
        entries = _accountable_entries(wp.tasks[nid])
        return max(float(jt.get("job", {}).get("hourlyRate") or 0) for jt in entries)
    return max(candidates, key=cost_of_a_role)


def apply(wp, target):
    task = wp.tasks[target]
    task["jobTasks"] = [jt for jt in (task.get("jobTasks") or []) if jt.get("role") != "A"]
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * WAIT_REDUCTION_FACTOR
    return [target.replace("Activity_", "")]