from .config import get_role_entry, LOW_PCT, has_external_authority_reference

NAME = "Empower"
WAIT_REDUCTION_FACTOR = 0.8


def qualify(wp):
    candidates = []
    for nid, task in wp.tasks.items():
        a_entry = get_role_entry(task, "A")
        r_entry = get_role_entry(task, "R")
        if a_entry is None or r_entry is None:
            continue

        a_rate = (a_entry.get("job") or {}).get("hourlyRate")
        r_rate = (r_entry.get("job") or {}).get("hourlyRate")
        if a_rate is None or r_rate is None or a_rate <= r_rate:
            continue
        if float(a_entry.get("time_allocation_percentage") or 0) > LOW_PCT:
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