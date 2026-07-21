from .config import unique_job_ids, unique_function_ids, PARTICIPANT_MAX, DEPT_MAX, NEGLIGIBLE_PCT, target_rule_results, existential_rule_results

NAME = "Numerical Involvement"
WAIT_REDUCTION_PER_ROLE = 0.05


def _too_many_people(task):
    return len(unique_job_ids(task)) >= PARTICIPANT_MAX


def _too_many_departments(task):
    return len(unique_function_ids(task)) >= DEPT_MAX


def qualify(wp):
    candidates = [nid for nid, task in wp.tasks.items() if _too_many_people(task) or _too_many_departments(task)]
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


def rule_checks(wp, target=None):
    rule_fns = [
        ("4 or more distinct people involved", lambda nid: _too_many_people(wp.tasks[nid])),
        ("3 or more distinct departments involved", lambda nid: _too_many_departments(wp.tasks[nid])),
    ]
    if target is not None:
        return target_rule_results(rule_fns, target[0] if isinstance(target, list) else target)
    return existential_rule_results(rule_fns, list(wp.tasks.keys()))