from .config import get_role_entry, has_external_authority_reference

NAME = "Bottleneck"
WAIT_REDUCTION_FACTOR = 0.5
COST_INCREASE_FACTOR = 1.15
UTILIZATION_THRESHOLD_PCT = 80


def _r_job_utilization(wp, job_id):
    total = 0.0
    for task in wp.tasks.values():
        for jt in task.get("jobTasks") or []:
            if jt.get("role") == "R" and jt.get("job_id") == job_id:
                total += float(jt.get("time_allocation_percentage") or 0)
    return total


def _topological_order(wp):
    incoming_count = {n: len(wp.incoming.get(n, [])) for n in wp.node_tags}
    queue = [n for n, c in incoming_count.items() if c == 0]
    order = []
    remaining = dict(incoming_count)
    idx = 0
    while idx < len(queue):
        node = queue[idx]
        idx += 1
        order.append(node)
        for nxt in wp.outgoing.get(node, []):
            remaining[nxt] -= 1
            if remaining[nxt] == 0:
                queue.append(nxt)
    for n in wp.node_tags:
        if n not in order:
            order.append(n)
    return order


def _reach_probabilities(wp):
    order = _topological_order(wp)
    reach = {wp.start: 1.0}

    for node in order:
        if node == wp.start:
            continue
        preds = wp.incoming.get(node, [])
        if not preds:
            continue

        is_parallel_join = any(
            p in wp.gateways and wp.gateways[p].gateway_type == "PARALLEL"
            for p in preds
        )

        values = []
        for p in preds:
            base = reach.get(p, 0.0)
            share = 1.0
            if p in wp.gateways:
                gw = wp.gateways[p]
                if gw.gateway_type != "PARALLEL":
                    share = gw.branch_probabilities.get(node, 1.0)
            values.append(base * share)

        reach[node] = max(values) if is_parallel_join else sum(values)

    return reach


def _total_time(task):
    process = float(task.get("expected_process_time") or 0)
    rework = float(task.get("expected_rework_time") or 0)
    waiting = float(task.get("expected_waiting_time") or 0)
    return process + rework + waiting


def qualify(wp):
    candidates = []
    for nid, task in wp.tasks.items():
        r_entry = get_role_entry(task, "R")
        utilization_hit = False
        if r_entry and r_entry.get("job_id") is not None:
            utilization = _r_job_utilization(wp, r_entry["job_id"])
            utilization_hit = utilization >= UTILIZATION_THRESHOLD_PCT

        waiting = float(task.get("expected_waiting_time") or 0)
        wait_hit = waiting > 0 and not has_external_authority_reference(task, wp)

        if utilization_hit or wait_hit:
            candidates.append(nid)

    if not candidates:
        return False, "No step's owner looks overloaded, and no internal step has a queue that extra staffing would help.", []
    return True, None, candidates


def select_target(wp, candidates):
    reach = _reach_probabilities(wp)

    def contribution(nid):
        return reach.get(nid, 0.0) * _total_time(wp.tasks[nid])

    return max(candidates, key=contribution)


def apply(wp, target):
    task = wp.tasks[target]
    task["expected_waiting_time"] = float(task.get("expected_waiting_time") or 0) * WAIT_REDUCTION_FACTOR

    for jt in task.get("jobTasks") or []:
        if jt.get("role") == "R":
            job = jt.get("job") or {}
            if job.get("hourlyRate") is not None:
                job["hourlyRate"] = float(job["hourlyRate"]) * COST_INCREASE_FACTOR

    return [target.replace("Activity_", "")]