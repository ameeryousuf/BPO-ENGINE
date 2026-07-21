from .config import get_role_entry, SMALL_STEP_MIN, target_rule_results, existential_rule_results

NAME = "Activity Composition"


def _same_r(task_a, task_b):
    ra = get_role_entry(task_a, "R")
    rb = get_role_entry(task_b, "R")
    if ra is None or rb is None:
        return False
    return ra.get("job_id") == rb.get("job_id")


def _all_adjacent_pairs(wp):
    pairs = []
    for a, targets in wp.outgoing.items():
        if wp.node_tags.get(a) != "task" or len(targets) != 1:
            continue
        b = targets[0]
        if wp.node_tags.get(b) != "task" or len(wp.incoming.get(b, [])) != 1:
            continue
        pairs.append((a, b))
    return pairs


def _both_small(pair, wp):
    a, b = pair
    time_a = float(wp.tasks[a].get("expected_process_time") or 0)
    time_b = float(wp.tasks[b].get("expected_process_time") or 0)
    return time_a <= SMALL_STEP_MIN and time_b <= SMALL_STEP_MIN


def _no_wait_between(pair, wp):
    a, _ = pair
    wait_a = wp.tasks[a].get("expected_waiting_time")
    return wait_a in (0, None)


def _pairs(wp):
    pairs = []
    for a, b in _all_adjacent_pairs(wp):
        if not _same_r(wp.tasks[a], wp.tasks[b]):
            continue
        if not _both_small((a, b), wp):
            continue
        if not _no_wait_between((a, b), wp):
            continue
        pairs.append((a, b))
    return pairs


def qualify(wp):
    pairs = _pairs(wp)
    if not pairs:
        return False, "No two small, back-to-back steps are both handled by the same person with no wait in between.", []
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


def rule_checks(wp, target=None):
    rule_fns = [
        ("Same person Responsible for both steps", lambda pair: _same_r(wp.tasks[pair[0]], wp.tasks[pair[1]])),
        ("Both steps are small enough to merge", lambda pair: _both_small(pair, wp)),
        ("No waiting time between the two steps", lambda pair: _no_wait_between(pair, wp)),
    ]
    if target is not None:
        return target_rule_results(rule_fns, target)
    return existential_rule_results(rule_fns, _all_adjacent_pairs(wp))