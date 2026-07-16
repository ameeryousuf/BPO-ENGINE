from __future__ import annotations

from bpmn_graph import GATEWAY_TAGS, detect_back_edges, elem_name, parse_bpmn_graph


def find_critical_paths(process_data: dict) -> list:
    graph = parse_bpmn_graph(process_data["bpmn_xml"])

    if len(graph.start_events) != 1:
        raise ValueError("process must have exactly one start event")

    tasks_by_activity = _build_task_index(process_data)
    back_edges = detect_back_edges(graph)
    back_edge_set = {(src, tgt) for src, tgt, _ in back_edges}

    scenarios = []
    _enumerate(graph.start_events[0], graph, back_edge_set, {}, scenarios)

    results = []
    for idx, (choices, _) in enumerate(scenarios, start=1):
        node_set, edges = _resolve_subgraph(graph, back_edge_set, choices)
        task_ids = [n for n in node_set if graph.is_task(n)]
        if not task_ids:
            continue

        order, adjacency = _topo_order(node_set, edges)
        es, ls, tct = _forward_backward(node_set, edges, adjacency, order, graph, tasks_by_activity)

        critical_ids = [
            n for n in task_ids
            if round(es[n], 4) == round(ls[n], 4)
        ]

        results.append({
            "scenario_id": f"S{idx}",
            "gateway_choices": choices,
            "theoretical_cycle_time": round(tct, 2),
            "critical_path_task_ids": [_clean_id(n) for n in critical_ids],
        })

    return results


def _clean_id(node_id: str) -> str:
    return node_id.replace("Activity_", "")


def _build_task_index(process_data: dict) -> dict:
    index = {}
    for pt in process_data.get("process_task", []):
        task = pt.get("task")
        if task is None:
            continue
        index[f"Activity_{pt['task_id']}"] = task
    return index


def _duration(node_id: str, graph, tasks_by_activity) -> float:
    if not graph.is_task(node_id):
        return 0.0
    task = tasks_by_activity.get(node_id)
    return float(task.get("expected_process_time") or 0) if task else 0.0


def _cartesian(list_of_dict_lists):
    result = [{}]
    for dict_list in list_of_dict_lists:
        new_result = []
        for r in result:
            for d in dict_list:
                merged = dict(r)
                merged.update(d)
                new_result.append(merged)
        result = new_result
    return result


def _common_join(graph, branch_starts, back_edge_set):
    reachable_sets = []
    for start in branch_starts:
        seen = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for f in graph.outgoing.get(node, []):
                tgt = f.get("targetRef")
                if (node, tgt) not in back_edge_set:
                    stack.append(tgt)
        reachable_sets.append(seen)

    common = set.intersection(*reachable_sets) if reachable_sets else set()
    if not common:
        return None

    seen = set()
    order = []
    stack = [branch_starts[0]]
    while stack:
        node = stack.pop(0)
        if node in seen:
            continue
        seen.add(node)
        if node in common:
            order.append(node)
        for f in graph.outgoing.get(node, []):
            tgt = f.get("targetRef")
            if (node, tgt) not in back_edge_set and tgt not in seen:
                stack.append(tgt)

    return order[0] if order else None


def _enumerate(node_id, graph, back_edge_set, choices, scenarios, stop=None):
    if node_id == stop or graph.is_end(node_id):
        scenarios.append((dict(choices), None))
        return

    flows = [f for f in graph.outgoing.get(node_id, []) if (node_id, f.get("targetRef")) not in back_edge_set]
    if not flows:
        scenarios.append((dict(choices), None))
        return

    tag = graph.tag_of(node_id)

    if tag == "parallelGateway" and len(flows) > 1:
        branch_starts = [f.get("targetRef") for f in flows]
        join = _common_join(graph, branch_starts, back_edge_set)

        branch_choice_sets = []
        for bstart in branch_starts:
            sub_scenarios = []
            _enumerate(bstart, graph, back_edge_set, {}, sub_scenarios, stop=join)
            branch_choice_sets.append([c for c, _ in sub_scenarios])

        combos = _cartesian(branch_choice_sets)
        for combo in combos:
            merged_choices = dict(choices)
            merged_choices.update(combo)
            if join is not None and join != stop:
                _enumerate(join, graph, back_edge_set, merged_choices, scenarios, stop=stop)
            else:
                scenarios.append((dict(merged_choices), None))
        return

    if len(flows) > 1:
        for f in flows:
            label = f.get("name") or f.get("targetRef")
            new_choices = dict(choices)
            new_choices[elem_name(graph.nodes[node_id])] = label
            _enumerate(f.get("targetRef"), graph, back_edge_set, new_choices, scenarios, stop=stop)
        return

    _enumerate(flows[0].get("targetRef"), graph, back_edge_set, choices, scenarios, stop=stop)


def _resolve_subgraph(graph, back_edge_set, choices):
    node_set = set()
    edges = []
    start = graph.start_events[0]
    stack = [start]
    seen = set()

    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        node_set.add(node)

        flows = [f for f in graph.outgoing.get(node, []) if (node, f.get("targetRef")) not in back_edge_set]
        tag = graph.tag_of(node)

        if tag in GATEWAY_TAGS and tag != "parallelGateway" and len(flows) > 1:
            name = elem_name(graph.nodes[node])
            chosen_label = choices.get(name)
            flows = [f for f in flows if (f.get("name") or f.get("targetRef")) == chosen_label]

        for f in flows:
            tgt = f.get("targetRef")
            edges.append((node, tgt))
            node_set.add(tgt)
            if tgt not in seen:
                stack.append(tgt)

    return node_set, edges


def _topo_order(node_set, edges):
    incoming_count = {n: 0 for n in node_set}
    adjacency = {n: [] for n in node_set}
    for src, tgt in edges:
        adjacency[src].append(tgt)
        incoming_count[tgt] += 1

    queue = [n for n in node_set if incoming_count[n] == 0]
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for nxt in adjacency[node]:
            incoming_count[nxt] -= 1
            if incoming_count[nxt] == 0:
                queue.append(nxt)

    return order, adjacency


def _forward_backward(node_set, edges, adjacency, order, graph, tasks_by_activity):
    predecessors = {n: [] for n in node_set}
    for src, tgt in edges:
        predecessors[tgt].append(src)

    es = {}
    ef = {}
    for node in order:
        preds = predecessors[node]
        es[node] = max((ef[p] for p in preds), default=0.0)
        ef[node] = es[node] + _duration(node, graph, tasks_by_activity)

    tct = max(ef.values()) if ef else 0.0

    lf = {}
    ls = {}
    for node in reversed(order):
        succs = adjacency[node]
        lf[node] = min((ls[s] for s in succs), default=tct)
        ls[node] = lf[node] - _duration(node, graph, tasks_by_activity)

    return es, ls, tct