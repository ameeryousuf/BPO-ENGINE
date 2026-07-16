from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from bpmn_graph import (
    BPMN_NS,
    BpmnSyntaxError,
    EVENT_END_TAGS,
    EVENT_START_TAGS,
    FLOW_NODE_TAGS,
    GATEWAY_TAGS,
    TASK_TAGS,
    elem_name,
    local,
    parse_bpmn_root,
)


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass
class Issue:
    severity: Severity
    code: str
    element_name: str
    element_id: str
    message: str

    def __str__(self) -> str:
        label = self.element_name or self.element_id or "(unknown)"
        return f"[{self.severity.value}] {self.code}: '{label}' — {self.message}"


@dataclass
class ValidationReport:
    process_id: int = None
    process_name: str = ""
    issues: list = field(default_factory=list)

    def add(self, severity: Severity, code: str, element_name: str,
            element_id: str, message: str) -> None:
        self.issues.append(Issue(severity, code, element_name, element_id, message))

    @property
    def errors(self) -> list:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def is_valid(self) -> bool:
        return not self.has_errors

    def to_dict(self) -> dict:
        return {
            "process_id": self.process_id,
            "process_name": self.process_name,
            "valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [
                {
                    "index": i,
                    "severity": issue.severity.value,
                    "code": issue.code,
                    "element_name": issue.element_name,
                    "element_id": issue.element_id,
                    "message": issue.message,
                }
                for i, issue in enumerate(self.issues, start=1)
            ],
        }


def validate_process(process_data: dict) -> ValidationReport:
    report = ValidationReport(
        process_id=process_data.get("process_id"),
        process_name=process_data.get("process_name", ""),
    )

    bpmn_xml = process_data.get("bpmn_xml")
    if not bpmn_xml:
        report.add(Severity.ERROR, "MISSING_BPMN", report.process_name,
                    "", "process record has no bpmn_xml field")
        return report

    try:
        root = parse_bpmn_root(bpmn_xml)
    except BpmnSyntaxError as e:
        report.add(Severity.ERROR, "XML_SYNTAX", report.process_name, "", str(e))
        return report

    process_elems = [el for el in root.iter() if local(el.tag) == "process"]
    if not process_elems:
        report.add(Severity.ERROR, "NO_PROCESS_ELEMENT", report.process_name,
                    "", "no <bpmn:process> element found in bpmn_xml")
        return report

    for process_el in process_elems:
        _validate_single_process(process_el, report)

    _validate_gateway_consistency(process_data, report)

    return report


def _validate_single_process(process_el, report: ValidationReport) -> None:
    nodes = {}
    for el in process_el:
        tag = local(el.tag)
        if tag in FLOW_NODE_TAGS:
            el_id = el.get("id")
            if not el_id:
                report.add(Severity.ERROR, "MISSING_ID", elem_name(el), "",
                            f"{tag} element has no id attribute")
                continue
            if el_id in nodes:
                report.add(Severity.ERROR, "DUPLICATE_ID", elem_name(el), el_id,
                            f"duplicate element id '{el_id}'")
            nodes[el_id] = el

    flows = [el for el in process_el if local(el.tag) == "sequenceFlow"]

    outgoing = {nid: [] for nid in nodes}
    incoming = {nid: [] for nid in nodes}

    flow_ids_seen = set()
    for flow in flows:
        fid = flow.get("id") or "(no-id)"
        if fid in flow_ids_seen:
            report.add(Severity.ERROR, "DUPLICATE_ID", fid, fid,
                        "duplicate sequenceFlow id")
        flow_ids_seen.add(fid)

        src = flow.get("sourceRef")
        tgt = flow.get("targetRef")

        if src is None or tgt is None:
            report.add(Severity.ERROR, "MALFORMED_FLOW", fid, fid,
                        "sequenceFlow missing sourceRef or targetRef")
            continue

        if src not in nodes:
            report.add(Severity.ERROR, "DANGLING_REF", fid, fid,
                        f"sourceRef '{src}' does not reference any known flow node")
        else:
            outgoing[src].append(flow)

        if tgt not in nodes:
            report.add(Severity.ERROR, "DANGLING_REF", fid, fid,
                        f"targetRef '{tgt}' does not reference any known flow node")
        else:
            incoming[tgt].append(flow)

        if src == tgt:
            report.add(Severity.ERROR, "SELF_LOOP", fid, fid,
                        f"sequenceFlow connects node '{src}' to itself")

    start_events = []
    end_events = []

    for node_id, el in nodes.items():
        tag = local(el.tag)
        name = elem_name(el)
        n_out = len(outgoing.get(node_id, []))
        n_in = len(incoming.get(node_id, []))

        if tag in EVENT_START_TAGS:
            start_events.append(node_id)
            if n_in > 0:
                report.add(Severity.ERROR, "START_HAS_INCOMING", name, node_id,
                            f"start event has {n_in} incoming edge(s); "
                            f"start events must have none")
            if n_out == 0:
                report.add(Severity.ERROR, "START_NO_OUTGOING", name, node_id,
                            "start event has no outgoing edge")
            elif n_out > 1:
                report.add(Severity.WARNING, "START_MULTIPLE_OUTGOING", name, node_id,
                            f"start event has {n_out} outgoing edges; "
                            f"unusual for a single start")

        elif tag in EVENT_END_TAGS:
            end_events.append(node_id)
            if n_out > 0:
                report.add(Severity.ERROR, "END_HAS_OUTGOING", name, node_id,
                            f"end event has {n_out} outgoing edge(s); "
                            f"end events must have none")
            if n_in == 0:
                report.add(Severity.WARNING, "END_NO_INCOMING", name, node_id,
                            "end event has no incoming edge (unreachable end)")

        elif tag in TASK_TAGS:
            if n_in == 0:
                report.add(Severity.ERROR, "TASK_NO_INCOMING", name, node_id,
                            f"task '{name}' has no incoming edge and is unreachable")
            if n_out == 0:
                report.add(Severity.ERROR, "TASK_NO_OUTGOING", name, node_id,
                            f"task '{name}' has no outgoing edge; "
                            f"process cannot continue past it")
            elif n_out > 1:
                report.add(Severity.ERROR, "TASK_MULTIPLE_OUTGOING", name, node_id,
                            f"task '{name}' has {n_out} outgoing edges, which is invalid — "
                            f"a plain task must have exactly one outgoing sequence flow. "
                            f"Use a gateway to split the flow instead.")
            if n_in > 1:
                report.add(Severity.WARNING, "TASK_MULTIPLE_INCOMING", name, node_id,
                            f"task '{name}' has {n_in} incoming edges; consider an "
                            f"explicit converging gateway for clarity")

        elif tag in GATEWAY_TAGS:
            is_diverging = n_out > 1
            is_converging = n_in > 1

            if n_in == 0:
                report.add(Severity.ERROR, "GATEWAY_NO_INCOMING", name, node_id,
                            f"gateway '{name}' has no incoming edge and is unreachable")
            if n_out == 0:
                report.add(Severity.ERROR, "GATEWAY_NO_OUTGOING", name, node_id,
                            f"gateway '{name}' has no outgoing edge")

            if is_diverging and is_converging:
                report.add(Severity.WARNING, "GATEWAY_MIXED", name, node_id,
                            f"gateway '{name}' both diverges ({n_out} out) and converges "
                            f"({n_in} in) in the same element; consider splitting into "
                            f"separate diverging/converging gateways for clarity")

            if tag == "exclusiveGateway" and is_diverging:
                unconditioned = [
                    f for f in outgoing[node_id]
                    if f.get("name") is None
                    and f.find(f"{BPMN_NS}conditionExpression") is None
                ]
                if len(unconditioned) > 1:
                    report.add(Severity.ERROR, "GATEWAY_MULTIPLE_DEFAULTS", name, node_id,
                                f"exclusive gateway '{name}' has {len(unconditioned)} "
                                f"outgoing branches with no condition/name — only one "
                                f"default branch is allowed")

    if len(start_events) == 0:
        report.add(Severity.ERROR, "NO_START_EVENT", report.process_name, "",
                    "process has no start event")
    elif len(start_events) > 1:
        report.add(Severity.WARNING, "MULTIPLE_START_EVENTS", report.process_name, "",
                    f"process has {len(start_events)} start events")

    if len(end_events) == 0:
        report.add(Severity.ERROR, "NO_END_EVENT", report.process_name, "",
                    "process has no end event")

    if start_events:
        reachable = set()
        stack = list(start_events)
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            for flow in outgoing.get(cur, []):
                tgt = flow.get("targetRef")
                if tgt and tgt not in reachable:
                    stack.append(tgt)

        for node_id, el in nodes.items():
            if node_id not in reachable:
                report.add(Severity.ERROR, "UNREACHABLE_NODE", elem_name(el), node_id,
                            f"'{elem_name(el)}' is not reachable from the start event")


def _validate_gateway_consistency(process_data: dict, report: ValidationReport) -> None:
    gateways = process_data.get("gateways") or []
    for gw in gateways:
        name = gw.get("name", "(unnamed gateway)")
        branches = gw.get("branches") or []

        if not branches:
            report.add(Severity.WARNING, "GATEWAY_NO_BRANCHES", name, "",
                        "structured gateway entry has no branches defined")
            continue

        probs = [b.get("probability") for b in branches if b.get("probability") is not None]
        if len(probs) == len(branches) and probs:
            total = round(sum(probs), 4)
            if abs(total - 1.0) > 0.001:
                report.add(Severity.ERROR, "PROBABILITY_SUM", name, "",
                            f"branch probabilities sum to {total}, expected 1.0")

        for branch in branches:
            targets_task = branch.get("target_task_id") is not None
            targets_end = bool(branch.get("end_event_name")) or branch.get("connect_to_end")
            if not targets_task and not targets_end:
                cond = branch.get("condition", "(no condition)")
                report.add(Severity.ERROR, "BRANCH_NO_TARGET", name, "",
                            f"branch '{cond}' has neither a target_task_id nor an "
                            f"end_event_name/connect_to_end — dangling branch")