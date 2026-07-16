from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

BPMN_NS = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"

TASK_TAGS = {
    "task", "serviceTask", "userTask", "scriptTask", "sendTask",
    "receiveTask", "manualTask", "businessRuleTask", "callActivity",
    "subProcess",
}
EVENT_START_TAGS = {"startEvent"}
EVENT_END_TAGS = {"endEvent"}
EVENT_INTERMEDIATE_TAGS = {"intermediateThrowEvent", "intermediateCatchEvent"}
GATEWAY_TAGS = {
    "exclusiveGateway", "inclusiveGateway", "parallelGateway",
    "eventBasedGateway", "complexGateway",
}
FLOW_NODE_TAGS = (
    TASK_TAGS | EVENT_START_TAGS | EVENT_END_TAGS
    | EVENT_INTERMEDIATE_TAGS | GATEWAY_TAGS
)


class BpmnSyntaxError(Exception):
    pass


def local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def elem_name(elem: ET.Element) -> str:
    return elem.get("name") or elem.get("id") or "(unnamed)"


def parse_bpmn_root(bpmn_xml: str) -> ET.Element:
    try:
        return ET.fromstring(bpmn_xml)
    except ET.ParseError as e:
        raise BpmnSyntaxError(f"bpmn_xml is not well-formed XML: {e}") from e


@dataclass
class BpmnGraph:
    nodes: dict = field(default_factory=dict)
    node_tags: dict = field(default_factory=dict)
    outgoing: dict = field(default_factory=dict)
    incoming: dict = field(default_factory=dict)
    start_events: list = field(default_factory=list)
    end_events: list = field(default_factory=list)

    def tag_of(self, node_id: str) -> str:
        return self.node_tags.get(node_id, "")

    def is_task(self, node_id: str) -> bool:
        return self.tag_of(node_id) in TASK_TAGS

    def is_gateway(self, node_id: str) -> bool:
        return self.tag_of(node_id) in GATEWAY_TAGS

    def is_end(self, node_id: str) -> bool:
        return self.tag_of(node_id) in EVENT_END_TAGS

    def successors(self, node_id: str) -> list:
        return [f.get("targetRef") for f in self.outgoing.get(node_id, [])]


def parse_bpmn_graph(bpmn_xml: str) -> BpmnGraph:
    root = parse_bpmn_root(bpmn_xml)
    process_el = next((el for el in root.iter() if local(el.tag) == "process"), None)
    if process_el is None:
        raise BpmnSyntaxError("no <bpmn:process> element found in bpmn_xml")

    graph = BpmnGraph()

    for el in process_el:
        tag = local(el.tag)
        if tag in FLOW_NODE_TAGS:
            node_id = el.get("id")
            if not node_id:
                continue
            graph.nodes[node_id] = el
            graph.node_tags[node_id] = tag
            graph.outgoing[node_id] = []
            graph.incoming[node_id] = []
            if tag in EVENT_START_TAGS:
                graph.start_events.append(node_id)
            elif tag in EVENT_END_TAGS:
                graph.end_events.append(node_id)

    for el in process_el:
        if local(el.tag) != "sequenceFlow":
            continue
        src = el.get("sourceRef")
        tgt = el.get("targetRef")
        if src in graph.nodes:
            graph.outgoing[src].append(el)
        if tgt in graph.nodes:
            graph.incoming[tgt].append(el)

    return graph


def detect_back_edges(graph: BpmnGraph):
    back_edges = []
    visited = set()
    on_stack = set()

    def dfs(node):
        visited.add(node)
        on_stack.add(node)
        for flow in graph.outgoing.get(node, []):
            target = flow.get("targetRef")
            if target in on_stack:
                back_edges.append((node, target, flow))
            elif target not in visited:
                dfs(target)
        on_stack.discard(node)

    for start in graph.start_events:
        if start not in visited:
            dfs(start)

    return back_edges