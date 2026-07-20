from .config import unique_job_ids

NAME = "Parallelism"


def _sequential_pairs(wp):
    pairs = []
    for a, targets in wp.outgoing.items():
        if wp.node_tags.get(a) != "task" or len(targets) != 1:
            continue
        b = targets[0]
        if wp.node_tags.get(b) != "task" or len(wp.incoming.get(b, [])) != 1:
            continue

        if unique_job_ids(wp.tasks[a]) & unique_job_ids(wp.tasks[b]):
            continue

        pairs.append((a, b))
    return pairs


def qualify(wp):
    pairs = _sequential_pairs(wp)
    if not pairs:
        return False, "There are no two neighboring steps, with completely different people involved, that could be safely run at the same time.", []
    return True, None, pairs


def select_target(wp, candidates):
    def gain(pair):
        a, b = pair
        ta = float(wp.tasks[a].get("expected_process_time") or 0)
        tb = float(wp.tasks[b].get("expected_process_time") or 0)
        return ta + tb - max(ta, tb)
    return max(candidates, key=gain)


def apply(wp, target):
    a, b = target
    pred = wp.incoming[a][0]
    succ = wp.outgoing[b][0]

    split_id = wp.new_id("Gateway")
    join_id = wp.new_id("Gateway")
    wp.add_gateway_node(split_id, "PARALLEL", f"Parallel Split {split_id}")
    wp.add_gateway_node(join_id, "PARALLEL", f"Parallel Join {join_id}")

    wp.replace_target(pred, a, split_id)
    wp.connect(split_id, a)
    wp.connect(split_id, b)
    wp.disconnect(a, b)
    wp.connect(a, join_id)
    wp.connect(b, join_id)
    wp.disconnect(b, succ)
    wp.connect(join_id, succ)

    return [a.replace("Activity_", ""), b.replace("Activity_", "")]