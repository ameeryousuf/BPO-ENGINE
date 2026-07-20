from .config import unique_job_ids, unique_function_ids, PARTICIPANT_MAX, DEPT_MAX, NEGLIGIBLE_PCT

NAME = "Numerical Involvement"
WAIT_REDUCTION_PER_ROLE = 0.05


def qualify(wp):
    candidates = []
    for nid, task in wp.tasks.items():
        if len(unique_job_ids(task)) >= PARTICIPANT_MAX or len(unique_function_ids(task)) >= DEPT_MAX:
            candidates.append(nid)

    if not candidates:
        return False, "No step involves more people or departments than necessary to get it done.", []
    return True, None, candidates


def select_target(wp, candidates):
    return max(candidates, key=lambda nid: len(unique_job_ids(wp.tasks[nid])))


def apply(wp, target):
    task = wp.tasks[target]
    job_tasks = task.get("jobTasks") or []

    kept = []
    removed_count = 0
    for jt in job_tasks:
        role = jt.get("role")
        pct = float(jt.get("time_allocation_percentage") or 0)
        if role in ("C", "I") and pct <= NEGLIGIBLE_PCT:
            removed_count += 1
            continue
        kept.append(jt)

    task["jobTasks"] = kept
    reduction = 1 - (WAIT_REDUCTION_PER_ROLE * max(removed_count, 0))
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * max(reduction, 0.5)
    return [target.replace("Activity_", "")]