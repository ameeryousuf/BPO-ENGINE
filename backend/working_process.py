from __future__ import annotations

import copy
from dataclasses import dataclass, field

from bpmn_graph import TASK_TAGS, elem_name, parse_bpmn_graph


@dataclass
class WGateway:
    node_id: str
    gateway_type: str
    branch_probabilities: dict = field(default_factory=dict)
    branch_conditions: dict = field(default_factory=dict)


@dataclass
class WorkingProcess:
    process_id: int
    process_name: str
    node_tags: dict = field(default_factory=dict)
    node_names: dict = field(default_factory=dict)
    outgoing: dict = field(default_factory=dict)
    incoming: dict = field(default_factory=dict)
    tasks: dict = field(default_factory=dict)
    gateways: dict = field(default_factory=dict)
    start: str = None
    ends: set = field(default_factory=set)
    id_counter: int = 1

    def new_id(self, prefix: str) -> str:
        nid = f"{prefix}_{self.id_counter}"
        self.id_counter += 1
        return nid

    def add_task_node(self, node_id, name, task_dict):
        self.node_tags[node_id] = "task"
        self.node_names[node_id] = name
        self.outgoing[node_id] = []
        self.incoming[node_id] = []
        self.tasks[node_id] = task_dict

    def add_gateway_node(self, node_id, gateway_type, name):
        tagmap = {"PARALLEL": "parallelGateway", "EXCLUSIVE": "exclusiveGateway", "INCLUSIVE": "inclusiveGateway"}
        self.node_tags[node_id] = tagmap[gateway_type]
        self.node_names[node_id] = name
        self.outgoing[node_id] = []
        self.incoming[node_id] = []
        self.gateways[node_id] = WGateway(node_id, gateway_type)

    def connect(self, src, tgt):
        self.outgoing.setdefault(src, []).append(tgt)
        self.incoming.setdefault(tgt, []).append(src)

    def disconnect(self, src, tgt):
        if src in self.outgoing and tgt in self.outgoing[src]:
            self.outgoing[src].remove(tgt)
        if tgt in self.incoming and src in self.incoming[tgt]:
            self.incoming[tgt].remove(src)
        if src in self.gateways:
            self.gateways[src].branch_probabilities.pop(tgt, None)
            self.gateways[src].branch_conditions.pop(tgt, None)

    def replace_target(self, src, old_target, new_target):
        if src in self.outgoing:
            self.outgoing[src] = [new_target if t == old_target else t for t in self.outgoing[src]]
        self.incoming.setdefault(new_target, [])
        if src not in self.incoming[new_target]:
            self.incoming[new_target].append(src)
        if old_target in self.incoming:
            self.incoming[old_target] = [s for s in self.incoming[old_target] if s != src]
        if src in self.gateways:
            gw = self.gateways[src]
            if old_target in gw.branch_probabilities:
                gw.branch_probabilities[new_target] = gw.branch_probabilities.pop(old_target)
            if old_target in gw.branch_conditions:
                gw.branch_conditions[new_target] = gw.branch_conditions.pop(old_target)

    def remove_node(self, node_id):
        preds = list(self.incoming.get(node_id, []))
        succs = list(self.outgoing.get(node_id, []))
        succ = succs[0] if succs else None

        if succ is not None:
            for p in preds:
                self.replace_target(p, node_id, succ)
            self.incoming[succ] = [s for s in self.incoming.get(succ, []) if s != node_id]
        else:
            for p in preds:
                self.disconnect(p, node_id)

        self.node_tags.pop(node_id, None)
        self.node_names.pop(node_id, None)
        self.outgoing.pop(node_id, None)
        self.incoming.pop(node_id, None)
        self.tasks.pop(node_id, None)
        self.gateways.pop(node_id, None)


def _find_end_node(node_tags, node_names, end_name):
    for nid, tag in node_tags.items():
        if tag == "endEvent" and node_names.get(nid) == end_name:
            return nid
    return None


def _build_flow_name_map(graph):
    mapping = {}
    for node_id, flows in graph.outgoing.items():
        for f in flows:
            mapping[(node_id, f.get("targetRef"))] = f.get("name")
    return mapping


def build_working_process(process_data: dict) -> WorkingProcess:
    graph = parse_bpmn_graph(process_data["bpmn_xml"])

    if len(graph.start_events) != 1:
        raise ValueError("process must have exactly one start event")

    flow_names = _build_flow_name_map(graph)

    node_tags = {}
    node_names = {}
    outgoing = {}
    incoming = {}

    for node_id, tag in graph.node_tags.items():
        node_tags[node_id] = "task" if tag in TASK_TAGS else tag
        node_names[node_id] = elem_name(graph.nodes[node_id])
        outgoing[node_id] = []
        incoming[node_id] = []

    for node_id, flows in graph.outgoing.items():
        for f in flows:
            outgoing[node_id].append(f.get("targetRef"))
    for node_id, flows in graph.incoming.items():
        for f in flows:
            incoming[node_id].append(f.get("sourceRef"))

    tasks = {}
    for pt in process_data.get("process_task", []):
        task = pt.get("task")
        if task is None:
            continue
        tasks[f"Activity_{pt['task_id']}"] = copy.deepcopy(task)

    gateway_by_name = {gw["name"]: gw for gw in process_data.get("gateways", [])}
    gateways = {}
    for node_id, tag in node_tags.items():
        if tag not in ("exclusiveGateway", "inclusiveGateway", "parallelGateway"):
            continue
        if tag == "parallelGateway":
            gateways[node_id] = WGateway(node_id, "PARALLEL")
            continue

        name = node_names[node_id]
        gw = gateway_by_name.get(name)
        branch_probs = {}
        branch_conds = {}
        if gw:
            for branch in gw.get("branches", []):
                target_id = None
                condition = branch.get("condition")

                if branch.get("target_task_id") is not None:
                    target_id = f"Activity_{branch['target_task_id']}"
                elif branch.get("end_event_name"):
                    target_id = _find_end_node(node_tags, node_names, branch["end_event_name"])

                if target_id is None and condition:
                    for tid in outgoing.get(node_id, []):
                        if flow_names.get((node_id, tid)) == condition:
                            target_id = tid
                            break

                if target_id is None:
                    unclaimed = [tid for tid in outgoing.get(node_id, []) if tid not in branch_probs]
                    if len(unclaimed) == 1:
                        target_id = unclaimed[0]

                if target_id is not None:
                    branch_probs[target_id] = float(branch.get("probability") or 0)
                    if condition:
                        branch_conds[target_id] = condition

        gateways[node_id] = WGateway(
            node_id,
            gw.get("gateway_type") if gw else "EXCLUSIVE",
            branch_probs,
            branch_conds,
        )

    max_task_id = max([int(k.split("_")[1]) for k in tasks.keys()] or [0])

    return WorkingProcess(
        process_id=process_data.get("process_id"),
        process_name=process_data.get("process_name", ""),
        node_tags=node_tags,
        node_names=node_names,
        outgoing=outgoing,
        incoming=incoming,
        tasks=tasks,
        gateways=gateways,
        start=graph.start_events[0],
        ends={n for n, t in node_tags.items() if t == "endEvent"},
        id_counter=max_task_id + 1,
    )