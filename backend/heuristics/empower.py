from .config import get_role_entry, LOW_PCT, has_external_authority_reference, target_rule_results, existential_rule_results

NAME = "Empower"
WAIT_REDUCTION_FACTOR = 0.8


def _a_more_senior_than_r(task):
    a_entry = get_role_entry(task, "A")
    r_entry = get_role_entry(task, "R")
    if a_entry is None or r_entry is None:
        return False
    a_rate = (a_entry.get("job") or {}).get("hourlyRate")
    r_rate = (r_entry.get("job") or {}).get("hourlyRate")
    return a_rate is not None and r_rate is not None and a_rate > r_rate


def _a_barely_engaged(task):
    a_entry = get_role_entry(task, "A")
    if a_entry is None:
        return False
    return float(a_entry.get("time_allocation_percentage") or 0) <= LOW_PCT


def qualify(wp):
    candidates = []
    for nid, task in wp.tasks.items():
        if not _a_more_senior_than_r(task):
            continue
        if not _a_barely_engaged(task):
            continue
        if has_external_authority_reference(task, wp):
            continue
        candidates.append(nid)

    if not candidates:
        return False, "There is no extra sign-off left that's both barely engaged and safe to remove.", []
    return True, None, candidates


def select_target(wp, candidates):
    def a_rate(nid):
        entry = get_role_entry(wp.tasks[nid], "A")
        return (entry.get("job") or {}).get("hourlyRate", 0)
    return max(candidates, key=a_rate)


def apply(wp, target):
    task = wp.tasks[target]
    task["jobTasks"] = [jt for jt in (task.get("jobTasks") or []) if jt.get("role") != "A"]
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * WAIT_REDUCTION_FACTOR
    return [target.replace("Activity_", "")]


def rule_checks(wp, target=None):
    rule_fns = [
        ("Accountable person is paid more than Responsible", lambda nid: _a_more_senior_than_r(wp.tasks[nid])),
        ("Accountable person is barely engaged", lambda nid: _a_barely_engaged(wp.tasks[nid])),
        ("Not a statutory/external approval", lambda nid: not has_external_authority_reference(wp.tasks[nid], wp)),
    ]
    if target is not None:
        return target_rule_results(rule_fns, target[0] if isinstance(target, list) else target)
    return existential_rule_results(rule_fns, list(wp.tasks.keys()))