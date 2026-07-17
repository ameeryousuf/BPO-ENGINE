NAME = "Numerical Involvement"
WAIT_REDUCTION_PER_ROLE = 0.05


def qualify(wp):
    candidates = [nid for nid, t in wp.tasks.items() if len(t.get("jobTasks") or []) > 2]
    if not candidates:
        return False, "No step involves more people than necessary to get it done.", []
    return True, None, candidates


def select_target(wp, candidates):
    return max(candidates, key=lambda nid: len(wp.tasks[nid].get("jobTasks") or []))


def apply(wp, target):
    task = wp.tasks[target]
    job_tasks = task.get("jobTasks") or []
    informed = [jt for jt in job_tasks if jt.get("role") == "I"]
    kept = [jt for jt in job_tasks if jt.get("role") != "I"]
    task["jobTasks"] = kept
    reduction = 1 - (WAIT_REDUCTION_PER_ROLE * max(len(informed), 1))
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * max(reduction, 0.5)
    return [target.replace("Activity_", "")]