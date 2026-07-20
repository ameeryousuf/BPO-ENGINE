from .config import AUTOMATION_KW, keyword_match, get_r_job, median_job_level

NAME = "Activity Automation"
TIME_FACTOR = 0.2
WAIT_FACTOR = 0.5


def qualify(wp):
    median_level = median_job_level(wp)
    candidates = []
    for nid, task in wp.tasks.items():
        text = f"{task.get('task_name', '')} {task.get('task_overview', '')}"
        if not keyword_match(text, AUTOMATION_KW):
            continue

        r_job = get_r_job(task)
        if r_job is None or median_level is None or r_job.get("job_level_id") is None:
            continue
        if r_job["job_level_id"] > median_level:
            continue

        c_count = sum(1 for jt in (task.get("jobTasks") or []) if jt.get("role") == "C")
        if c_count > 0:
            continue

        candidates.append(nid)

    if not candidates:
        return False, "No remaining step both sounds automatable and is simple enough (junior-level owner, nobody consulted) to hand to a system.", []
    return True, None, candidates


def select_target(wp, candidates):
    return max(candidates, key=lambda nid: float(wp.tasks[nid].get("expected_process_time") or 0))


def apply(wp, target):
    task = wp.tasks[target]
    task["expected_process_time"] = float(task.get("expected_process_time") or 0) * TIME_FACTOR
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * WAIT_FACTOR
    task["jobTasks"] = [jt for jt in (task.get("jobTasks") or []) if jt.get("role") in ("A", "I")]
    return [target.replace("Activity_", "")]