import json
import networkx as nx


def load_process(json_path: str) -> dict:
    with open(json_path, "r") as f:
        return json.load(f)


def build_graph(data: dict) -> nx.DiGraph:
    g = nx.DiGraph()
    g.graph["process_id"] = data.get("process_id")
    g.graph["process_name"] = data.get("process_name")

    tasks = data["process_task"]
    gateways = data.get("gateways", [])

    for pt in tasks:
        t = pt.get("task", {}) or {}
        task_id = pt["task_id"]
        jts = t.get("jobTasks") or []
        raci = [
            {
                "role": jt.get("role"),
                "pct": jt.get("time_allocation_percentage"),
                "job_name": (jt.get("job") or {}).get("name"),
                "hourly_rate": (jt.get("job") or {}).get("hourlyRate"),
            }
            for jt in jts
        ]
        g.add_node(
            task_id,
            kind="task",
            order=pt.get("order"),
            task_code=t.get("task_code"),
            task_name=t.get("task_name"),
            value_classification=pt.get("value_classification"),
            process_time=t.get("expected_process_time") or 0,
            rework_time=t.get("expected_rework_time") or 0,
            waiting_time=t.get("expected_waiting_time") or 0,
            extra_cost=0.0,
            raci=raci,
        )

    for gw in gateways:
        gid = gw["gateway_pk_id"]
        g.add_node(
            gid,
            kind="gateway",
            gateway_type=gw.get("gateway_type"),
            name=gw.get("name"),
            after_task_id=gw.get("after_task_id"),
            after_gateway_id=gw.get("after_gateway_id"),
        )

    g.add_node("START", kind="start")
    g.add_node("END", kind="end")

    for gw in gateways:
        gid = gw["gateway_pk_id"]
        if gw.get("after_task_id") is not None:
            g.add_edge(gw["after_task_id"], gid)
        elif gw.get("after_gateway_id") is not None:
            g.add_edge(gw["after_gateway_id"], gid)


    for gw in gateways:
        gid = gw["gateway_pk_id"]
        for b in gw.get("branches", []):
            attrs = {"condition": b.get("condition"), "probability": b.get("probability")}
            if b.get("target_task_id") is not None:
                g.add_edge(gid, b["target_task_id"], **attrs)
            elif b.get("target_gateway_id") is not None:
                g.add_edge(gid, b["target_gateway_id"], **attrs)
            elif b.get("connect_to_end"):
                g.add_edge(gid, "END", **attrs)


    tasks_sorted = sorted(tasks, key=lambda pt: pt.get("order") or 0)
    gateway_after_task_ids = {gw["after_task_id"] for gw in gateways if gw.get("after_task_id") is not None}
    task_ids_in_order = [pt["task_id"] for pt in tasks_sorted]


    branch_target_task_ids = set()
    for gw in gateways:
        for b in gw.get("branches", []):
            if b.get("target_task_id") is not None:
                branch_target_task_ids.add(b["target_task_id"])

    for i, tid in enumerate(task_ids_in_order):
        if tid in gateway_after_task_ids:
            continue
        if g.out_degree(tid) > 0:
            continue  
        next_tid = task_ids_in_order[i + 1] if i + 1 < len(task_ids_in_order) else None
        if next_tid is not None and next_tid not in branch_target_task_ids:
            g.add_edge(tid, next_tid)
        else:
            g.add_edge(tid, "END")


    for n, kind in list(g.nodes(data="kind")):
        if kind in ("task", "gateway") and g.out_degree(n) == 0:
            g.add_edge(n, "END")

    for n, kind in g.nodes(data="kind"):
        if n in ("START", "END"):
            continue
        if g.in_degree(n) == 0:
            g.add_edge("START", n)

    return g


def summarize_graph(g: nx.DiGraph) -> str:
    lines = [f"Process: {g.graph.get('process_name')} (id={g.graph.get('process_id')})"]
    lines.append(f"Nodes: {g.number_of_nodes()}  Edges: {g.number_of_edges()}")
    lines.append("")
    lines.append("Edges:")
    for u, v, attrs in g.edges(data=True):
        u_label = g.nodes[u].get("task_code") or g.nodes[u].get("name") or u
        v_label = g.nodes[v].get("task_code") or g.nodes[v].get("name") or v
        cond = attrs.get("condition")
        prob = attrs.get("probability")
        extra = f"  [{cond}, p={prob}]" if cond else ""
        lines.append(f"  {u_label} -> {v_label}{extra}")
    return "\n".join(lines)


if __name__ == "__main__":
    data = load_process("data/asIsProcess.json")
    graph = build_graph(data)
    print(summarize_graph(graph))