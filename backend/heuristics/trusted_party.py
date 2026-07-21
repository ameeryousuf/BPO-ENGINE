from .config import has_external_authority_reference, is_pass_fail_gateway, successor_of, target_rule_results, existential_rule_results

NAME = "Trusted Party"


def _has_wait(task):
    return float(task.get("expected_waiting_time") or 0) > 0


def _leads_to_pass_fail(nid, wp):
    gw_node = successor_of(wp, nid)
    return gw_node is not None and gw_node in wp.gateways and is_pass_fail_gateway(wp, gw_node)


def qualify(wp):
    candidates = []
    for nid, task in wp.tasks.items():
        if not has_external_authority_reference(task, wp):
            continue
        if not _has_wait(task):
            continue
        if not _leads_to_pass_fail(nid, wp):
            continue
        candidates.append(nid)

    if not candidates:
        return False, "No step depends on an outside party's decision that flows into a simple pass/fail check.", []
    return True, None, candidates


def select_target(wp, candidates):
    return max(candidates, key=lambda nid: float(wp.tasks[nid].get("expected_waiting_time") or 0))


def apply(wp, target):
    task = wp.tasks[target]
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * 0.1
    task["expected_process_time"] = float(task.get("expected_process_time") or 0) * 0.7
    return [target.replace("Activity_", "")]


def rule_checks(wp, target=None):
    rule_fns = [
        ("References an authority outside the company", lambda nid: has_external_authority_reference(wp.tasks[nid], wp)),
        ("Has real waiting time", lambda nid: _has_wait(wp.tasks[nid])),
        ("Leads to a simple pass/fail decision", lambda nid: _leads_to_pass_fail(nid, wp)),
    ]
    if target is not None:
        return target_rule_results(rule_fns, target[0] if isinstance(target, list) else target)
    return existential_rule_results(rule_fns, list(wp.tasks.keys()))