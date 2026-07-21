from .config import get_role_entry, NEGLIGIBLE_PCT, target_rule_results, existential_rule_results

NAME = "Activity Elimination"


def _is_gateway_adjacent(wp, node_id):
    for p in wp.incoming.get(node_id, []):
        if p in wp.gateways:
            return True
    for s in wp.outgoing.get(node_id, []):
        if s in wp.gateways:
            return True
    return False


def _no_real_owner(task):
    r_entry = get_role_entry(task, "R")
    a_entry = get_role_entry(task, "A")
    no_owner = r_entry is None and a_entry is None
    negligible_r = r_entry is not None and float(r_entry.get("time_allocation_percentage") or 0) <= NEGLIGIBLE_PCT
    return no_owner or negligible_r


def qualify(wp):
    candidates = []
    for nid, task in wp.tasks.items():
        if not _no_real_owner(task):
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


def rule_checks(wp, target=None):
    rule_fns = [
        ("No clear Responsible/Accountable owner", lambda nid: _no_real_owner(wp.tasks[nid])),
        ("Not directly next to a decision gateway", lambda nid: not _is_gateway_adjacent(wp, nid)),
    ]
    if target is not None:
        return target_rule_results(rule_fns, target)
    return existential_rule_results(rule_fns, list(wp.tasks.keys()))