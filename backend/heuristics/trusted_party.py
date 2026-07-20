from .config import has_external_authority_reference, is_pass_fail_gateway, successor_of

NAME = "Trusted Party"


def qualify(wp):
    candidates = []
    for nid, task in wp.tasks.items():
        if not has_external_authority_reference(task, wp):
            continue
        if float(task.get("expected_waiting_time") or 0) <= 0:
            continue

        gw_node = successor_of(wp, nid)
        if gw_node is None or gw_node not in wp.gateways or not is_pass_fail_gateway(wp, gw_node):
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