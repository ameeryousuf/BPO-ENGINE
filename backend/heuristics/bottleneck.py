NAME = "Bottleneck"
WAIT_REDUCTION_FACTOR = 0.5
COST_INCREASE_FACTOR = 1.15


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
    candidates = [
        nid for nid, t in wp.tasks.items()
        if float(t.get("expected_waiting_time") or 0) > 0
    ]
    if not candidates:
        return False, "No step has any waiting time that extra capacity could actually reduce.", []
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