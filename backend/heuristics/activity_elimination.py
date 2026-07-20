from .config import get_role_entry, NEGLIGIBLE_PCT

NAME = "Activity Elimination"


def _is_gateway_adjacent(wp, node_id):
    for p in wp.incoming.get(node_id, []):
        if p in wp.gateways:
            return True
    for s in wp.outgoing.get(node_id, []):
        if s in wp.gateways:
            return True
    return False


def qualify(wp):
    candidates = []
    for nid, task in wp.tasks.items():
        r_entry = get_role_entry(task, "R")
        a_entry = get_role_entry(task, "A")
        no_owner = r_entry is None and a_entry is None
        negligible_r = r_entry is not None and float(r_entry.get("time_allocation_percentage") or 0) <= NEGLIGIBLE_PCT

        if not (no_owner or negligible_r):
            continue
        if _is_gateway_adjacent(wp, nid):
            continue
        candidates.append(nid)

    if not candidates:
        return False, "Every remaining task has a real owner, or sits right next to a decision point where removing it would be unsafe.", []
    return True, None, candidates


def select_target(wp, candidates):
    def total_time(nid):
        t = wp.tasks[nid]
        return float(t.get("expected_process_time") or 0) + float(t.get("expected_rework_time") or 0)
    return max(candidates, key=total_time)


def apply(wp, target):
    removed = target.replace("Activity_", "")
    wp.remove_node(target)
    return [removed]