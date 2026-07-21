from .config import AUTOMATION_KW, keyword_match, get_r_job, median_job_level, target_rule_results, existential_rule_results

NAME = "Activity Automation"
TIME_FACTOR = 0.2
WAIT_FACTOR = 0.5


def _matches_keyword(task):
    text = f"{task.get('task_name', '')} {task.get('task_overview', '')}"
    return keyword_match(text, AUTOMATION_KW)


def _junior_owner(task, median_level):
    r_job = get_r_job(task)
    if r_job is None or median_level is None or r_job.get("job_level_id") is None:
        return False
    return r_job["job_level_id"] <= median_level


def _no_consulted(task):
    return sum(1 for jt in (task.get("jobTasks") or []) if jt.get("role") == "C") == 0


def qualify(wp):
    median_level = median_job_level(wp)
    candidates = []
    for nid, task in wp.tasks.items():
        if not _matches_keyword(task):
            continue
        if not _junior_owner(task, median_level):
            continue
        if not _no_consulted(task):
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


def rule_checks(wp, target=None):
    median_level = median_job_level(wp)
    rule_fns = [
        ("Task name/description sounds automatable", lambda nid: _matches_keyword(wp.tasks[nid])),
        ("Responsible person is at or below median seniority", lambda nid: _junior_owner(wp.tasks[nid], median_level)),
        ("Nobody is Consulted on this step", lambda nid: _no_consulted(wp.tasks[nid])),
    ]
    if target is not None:
        return target_rule_results(rule_fns, target[0] if isinstance(target, list) else target)
    return existential_rule_results(rule_fns, list(wp.tasks.keys()))