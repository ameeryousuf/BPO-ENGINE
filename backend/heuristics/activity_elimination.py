NAME = "Activity Elimination"


def _has_no_owner(task):
    roles = [jt.get("role") for jt in task.get("jobTasks") or []]
    return "R" not in roles and "A" not in roles


def qualify(wp):
    candidates = [nid for nid, t in wp.tasks.items() if _has_no_owner(t)]
    if not candidates:
        return False, "Every remaining task has someone clearly responsible for it, so none can be safely dropped.", []
    return True, None, candidates


def select_target(wp, candidates):
    return max(candidates, key=lambda nid: float(wp.tasks[nid].get("expected_process_time") or 0))


def apply(wp, target):
    removed = target.replace("Activity_", "")
    wp.remove_node(target)
    return [removed]