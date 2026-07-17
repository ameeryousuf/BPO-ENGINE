from __future__ import annotations

import xml.etree.ElementTree as ET

BPMN_NS_URI = "http://www.omg.org/spec/BPMN/20100524/MODEL"
ET.register_namespace("bpmn", BPMN_NS_URI)


def working_process_to_json(wp) -> dict:
    ns = "{%s}" % BPMN_NS_URI
    definitions = ET.Element(f"{ns}definitions")
    process_el = ET.SubElement(definitions, f"{ns}process", {"id": "Process_TOBE", "isExecutable": "true"})

    for node_id, tag in wp.node_tags.items():
        ET.SubElement(process_el, f"{ns}{tag}", {"id": node_id, "name": wp.node_names.get(node_id, node_id)})

    flow_counter = 0
    gateways_array = []

    for gw_id, gw in wp.gateways.items():
        branches = []
        for target in wp.outgoing.get(gw_id, []):
            condition = gw.branch_conditions.get(target)
            probability = gw.branch_probabilities.get(target)
            flow_counter += 1
            attrs = {"id": f"Flow_{flow_counter}", "sourceRef": gw_id, "targetRef": target}
            if condition:
                attrs["name"] = condition
            ET.SubElement(process_el, f"{ns}sequenceFlow", attrs)

            branch = {
                "target_task_id": None,
                "end_event_name": None,
                "connect_to_end": False,
                "condition": condition,
                "probability": probability,
            }
            if wp.node_tags.get(target) == "task":
                branch["target_task_id"] = int(target.split("_")[1])
            elif wp.node_tags.get(target) == "endEvent":
                branch["end_event_name"] = wp.node_names.get(target)
                branch["connect_to_end"] = True
            else:
                branch["connect_to_end"] = True
            branches.append(branch)

        gateways_array.append({
            "name": wp.node_names.get(gw_id, gw_id),
            "gateway_type": gw.gateway_type,
            "branches": branches,
        })

    for node_id, targets in wp.outgoing.items():
        if node_id in wp.gateways:
            continue
        for target in targets:
            flow_counter += 1
            ET.SubElement(process_el, f"{ns}sequenceFlow", {
                "id": f"Flow_{flow_counter}", "sourceRef": node_id, "targetRef": target,
            })

    bpmn_xml = ET.tostring(definitions, encoding="unicode")

    process_task = []
    for idx, (node_id, task) in enumerate(wp.tasks.items(), start=1):
        process_task.append({
            "process_task_id": idx,
            "task_id": int(node_id.split("_")[1]),
            "order": idx,
            "task": task,
        })

    return {
        "process_id": wp.process_id,
        "process_name": wp.process_name,
        "bpmn_xml": bpmn_xml,
        "gateways": gateways_array,
        "process_task": process_task,
    }