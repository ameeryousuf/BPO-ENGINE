NAME = "Activity Composition"


def _responsible_job_id(task):
    for jt in task.get("jobTasks") or []:
        if jt.get("role") == "R":
            return jt.get("job_id")
    return None


def _sequential_same_owner_pairs(wp):
    pairs = []
    for a, targets in wp.outgoing.items():
        if wp.node_tags.get(a) != "task" or len(targets) != 1:
            continue
        b = targets[0]
        if wp.node_tags.get(b) != "task" or len(wp.incoming.get(b, [])) != 1:
            continue
        owner_a = _responsible_job_id(wp.tasks[a])
        owner_b = _responsible_job_id(wp.tasks[b])
        if owner_a is not None and owner_a == owner_b:
            pairs.append((a, b))
    return pairs


def qualify(wp):
    pairs = _sequential_same_owner_pairs(wp)
    if not pairs:
        return False, "No two consecutive steps are handled by the same person in a way that could be combined.", []
    return True, None, pairs


def select_target(wp, candidates):
    def saving(pair):
        a, b = pair
        ta = float(wp.tasks[a].get("expected_process_time") or 0)
        tb = float(wp.tasks[b].get("expected_process_time") or 0)
        return min(ta, tb) * 0.1
    return max(candidates, key=saving)


def apply(wp, target):
    a, b = target
    ta = wp.tasks[a]
    tb = wp.tasks[b]
    setup_saving = min(float(ta.get("expected_process_time") or 0), float(tb.get("expected_process_time") or 0)) * 0.1

    merged_job_tasks = {}
    role_rank = {"R": 3, "A": 2, "C": 1, "I": 0}
    for jt in (ta.get("jobTasks") or []) + (tb.get("jobTasks") or []):
        job_id = jt.get("job_id")
        if job_id not in merged_job_tasks or role_rank.get(jt.get("role"), 0) > role_rank.get(merged_job_tasks[job_id].get("role"), 0):
            merged_job_tasks[job_id] = jt

    pred = wp.incoming[a][0]
    succ = wp.outgoing[b][0]

    merged_id = wp.new_id("Activity")
    merged_task = {
        "task_id": int(merged_id.split("_")[1]),
        "task_name": f"{ta.get('task_name', 'Task')} + {tb.get('task_name', 'Task')}",
        "expected_process_time": float(ta.get("expected_process_time") or 0) + float(tb.get("expected_process_time") or 0) - setup_saving,
        "expected_rework_time": float(ta.get("expected_rework_time") or 0) + float(tb.get("expected_rework_time") or 0),
        "expected_waiting_time": float(ta.get("expected_waiting_time") or 0) + float(tb.get("expected_waiting_time") or 0),
        "jobTasks": list(merged_job_tasks.values()),
    }

    wp.add_task_node(merged_id, merged_task["task_name"], merged_task)
    wp.replace_target(pred, a, merged_id)
    wp.disconnect(a, b)
    wp.disconnect(b, succ)
    wp.connect(merged_id, succ)

    del wp.tasks[a]
    del wp.tasks[b]
    for nid in (a, b):
        wp.node_tags.pop(nid, None)
        wp.node_names.pop(nid, None)
        wp.outgoing.pop(nid, None)
        wp.incoming.pop(nid, None)

    return [merged_id.replace("Activity_", "")]