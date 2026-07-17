from __future__ import annotations

import xml.etree.ElementTree as ET

BPMN_NS_URI = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS_URI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS_URI = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS_URI = "http://www.omg.org/spec/DD/20100524/DI"
BIOC_NS_URI = "http://bpmn.io/schema/bpmn/biocolor/1.0"
COLOR_NS_URI = "http://www.omg.org/spec/BPMN/non-normative/color/1.0"

ET.register_namespace("bpmn", BPMN_NS_URI)
ET.register_namespace("bpmndi", BPMNDI_NS_URI)
ET.register_namespace("dc", DC_NS_URI)
ET.register_namespace("di", DI_NS_URI)
ET.register_namespace("bioc", BIOC_NS_URI)
ET.register_namespace("color", COLOR_NS_URI)

GAP_X = 80
MARGIN_X = 60
MARGIN_Y = 40
LANE_PADDING_TOP = 60
LANE_PADDING_BOTTOM = 55
ROW_GAP = 30
MIN_LANE_HEIGHT = 140
CHANNEL_CLEARANCE = 52

AVG_CHAR_WIDTH = 6.5
TASK_PADDING_X = 24
TASK_PADDING_Y = 20
LINE_HEIGHT = 16
MIN_TASK_WIDTH = 120
MAX_TASK_WIDTH = 220
MIN_TASK_HEIGHT = 80

POOL_STYLE = {"stroke": "#1A237E", "fill": "#E8EAF6"}

PALETTE = [
    {"stroke": "#1565C0", "task_fill": "#BBDEFB", "lane_fill": "#E3F2FD"},
    {"stroke": "#2E7D32", "task_fill": "#C8E6C9", "lane_fill": "#E8F5E9"},
    {"stroke": "#EF6C00", "task_fill": "#FFE0B2", "lane_fill": "#FFF3E0"},
    {"stroke": "#6A1B9A", "task_fill": "#E1BEE7", "lane_fill": "#F3E5F5"},
    {"stroke": "#00838F", "task_fill": "#B2EBF2", "lane_fill": "#E0F7FA"},
]


def _wrap_line_count(name, max_chars_per_line):
    words = name.split()
    if not words:
        return 1

    lines = 1
    current_len = 0
    for word in words:
        added_len = len(word) + (1 if current_len > 0 else 0)
        if current_len + added_len <= max_chars_per_line:
            current_len += added_len
        else:
            lines += 1
            current_len = len(word)
    return lines


def _measure_task_box(name):
    name = name or ""
    single_line_width = len(name) * AVG_CHAR_WIDTH + TASK_PADDING_X

    if single_line_width <= MAX_TASK_WIDTH:
        width = max(MIN_TASK_WIDTH, single_line_width)
        return round(width), MIN_TASK_HEIGHT

    max_chars_per_line = max(1, int((MAX_TASK_WIDTH - TASK_PADDING_X) / AVG_CHAR_WIDTH))
    line_count = _wrap_line_count(name, max_chars_per_line)
    height = max(MIN_TASK_HEIGHT, line_count * LINE_HEIGHT + TASK_PADDING_Y * 2)
    return MAX_TASK_WIDTH, round(height)


def _node_size(tag, name=None):
    if tag == "task":
        return _measure_task_box(name)
    if tag in ("startEvent", "endEvent"):
        return (36, 36)
    return (50, 50)


def _topo_order(wp):
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


def _compute_layers(wp, order):
    layer = {}
    for node in order:
        preds = wp.incoming.get(node, [])
        if not preds:
            layer[node] = 0
        else:
            layer[node] = max(layer.get(p, 0) for p in preds) + 1
    return layer


def _task_owner_name(task):
    job_tasks = task.get("jobTasks") or []
    for role in ("R", "A"):
        for jt in job_tasks:
            if jt.get("role") == role:
                job = jt.get("job") or {}
                return job.get("name") or f"Job {jt.get('job_id')}"
    return "Unassigned"


def _assign_lanes(wp):
    order = _topo_order(wp)
    task_order = [n for n in order if wp.node_tags.get(n) == "task"]

    lane_of = {}
    lanes_order = []

    for t in task_order:
        name = _task_owner_name(wp.tasks[t])
        if name not in lanes_order:
            lanes_order.append(name)
        lane_of[t] = name

    def resolve(node, visited):
        if node in lane_of:
            return lane_of[node]
        if node in visited:
            return None
        visited.add(node)
        for p in wp.incoming.get(node, []):
            found = resolve(p, visited)
            if found:
                lane_of[node] = found
                return found
        for s in wp.outgoing.get(node, []):
            found = resolve(s, visited)
            if found:
                lane_of[node] = found
                return found
        return None

    for node in order:
        if node not in lane_of:
            resolve(node, set())

    if not lanes_order:
        lanes_order = ["General"]
    for node in wp.node_tags:
        if node not in lane_of:
            lane_of[node] = lanes_order[0]

    return lane_of, lanes_order


def _compute_layout(wp, lane_of, lanes_order):
    order = _topo_order(wp)
    layer = _compute_layers(wp, order)
    lane_index = {name: i for i, name in enumerate(lanes_order)}

    sizes = {n: _node_size(wp.node_tags[n], wp.node_names.get(n)) for n in order}

    layer_width = {}
    for node in order:
        l = layer[node]
        w = sizes[node][0]
        layer_width[l] = max(layer_width.get(l, 0), w)

    max_layer = max(layer_width.keys(), default=0)
    layer_x = {}
    cursor = MARGIN_X
    for l in range(max_layer + 1):
        layer_x[l] = cursor
        cursor += layer_width.get(l, 0) + GAP_X

    lane_row_step = {name: MIN_TASK_HEIGHT + ROW_GAP for name in lanes_order}
    for node in order:
        lane_name = lane_of.get(node, lanes_order[0])
        h = sizes[node][1]
        lane_row_step[lane_name] = max(lane_row_step[lane_name], h + ROW_GAP)

    occupancy = {}
    row_used = {name: 0 for name in lanes_order}
    node_row = {}
    for node in order:
        lane_name = lane_of.get(node, lanes_order[0])
        l = layer[node]
        key = (lane_name, l)
        row = occupancy.get(key, 0)
        occupancy[key] = row + 1
        node_row[node] = row
        row_used[lane_name] = max(row_used[lane_name], row + 1)

    lane_height = {}
    lane_top = {}
    cursor_y = MARGIN_Y
    for lane_name in lanes_order:
        lane_top[lane_name] = cursor_y
        rows = max(1, row_used[lane_name])
        height = max(MIN_LANE_HEIGHT, rows * lane_row_step[lane_name] + LANE_PADDING_TOP + LANE_PADDING_BOTTOM)
        lane_height[lane_name] = height
        cursor_y += height

    boxes = {}
    for node in order:
        lane_name = lane_of.get(node, lanes_order[0])
        l = layer[node]
        w, h = sizes[node]
        x = layer_x[l] + (layer_width[l] - w) / 2
        row = node_row[node]
        row_step = lane_row_step[lane_name]
        row_top = lane_top[lane_name] + LANE_PADDING_TOP + row * row_step
        y = row_top + (row_step - ROW_GAP - h) / 2
        boxes[node] = (x, y, w, h)

    total_width = cursor - GAP_X + MARGIN_X
    total_height = cursor_y + CHANNEL_CLEARANCE

    return boxes, lane_index, lane_top, lane_height, total_width, total_height


def _lane_boundaries(lanes_order, lane_top, lane_height):
    boundaries = [lane_top[lanes_order[0]] - CHANNEL_CLEARANCE]
    for i in range(len(lanes_order) - 1):
        name = lanes_order[i]
        seam = lane_top[name] + lane_height[name]
        boundaries.append(seam - CHANNEL_CLEARANCE)
        boundaries.append(seam + CHANNEL_CLEARANCE)
    last = lanes_order[-1]
    boundaries.append(lane_top[last] + lane_height[last] + CHANNEL_CLEARANCE)
    return boundaries


def _h_segment_clear(y, x1, x2, obstacles):
    lo, hi = min(x1, x2), max(x1, x2)
    for (bx, by, bw, bh) in obstacles.values():
        if by <= y <= by + bh and hi >= bx and lo <= bx + bw:
            return False
    return True


def _v_segment_clear(x, y1, y2, obstacles):
    lo, hi = min(y1, y2), max(y1, y2)
    for (bx, by, bw, bh) in obstacles.values():
        if bx <= x <= bx + bw and hi >= by and lo <= by + bh:
            return False
    return True


def _route_edge(src_id, tgt_id, boxes, lane_boundaries):
    sx, sy, sw, sh = boxes[src_id]
    tx, ty, tw, th = boxes[tgt_id]
    src_point = (sx + sw, sy + sh / 2)
    tgt_point = (tx, ty + th / 2)
    obstacles = {k: v for k, v in boxes.items() if k not in (src_id, tgt_id)}

    if abs(src_point[1] - tgt_point[1]) < 1:
        if _h_segment_clear(src_point[1], src_point[0], tgt_point[0], obstacles):
            return [src_point, tgt_point]

    mid_x = (src_point[0] + tgt_point[0]) / 2
    direct_route = [src_point, (mid_x, src_point[1]), (mid_x, tgt_point[1]), tgt_point]
    if (
        _h_segment_clear(src_point[1], src_point[0], mid_x, obstacles)
        and _v_segment_clear(mid_x, src_point[1], tgt_point[1], obstacles)
        and _h_segment_clear(tgt_point[1], mid_x, tgt_point[0], obstacles)
    ):
        return direct_route

    sorted_channels = sorted(
        lane_boundaries,
        key=lambda cy: min(abs(cy - src_point[1]), abs(cy - tgt_point[1])),
    )
    for channel_y in sorted_channels:
        route = [src_point, (src_point[0], channel_y), (tgt_point[0], channel_y), tgt_point]
        if (
            _v_segment_clear(src_point[0], src_point[1], channel_y, obstacles)
            and _h_segment_clear(channel_y, src_point[0], tgt_point[0], obstacles)
            and _v_segment_clear(tgt_point[0], channel_y, tgt_point[1], obstacles)
        ):
            return route

    return direct_route


def _color_for(tag, lane_idx):
    style = PALETTE[lane_idx % len(PALETTE)]
    if tag == "task":
        return style["stroke"], style["task_fill"]
    if tag in ("exclusiveGateway", "inclusiveGateway", "parallelGateway"):
        return style["stroke"], "#FFFFFF"
    return None, None


def working_process_to_json(wp) -> dict:
    ns = "{%s}" % BPMN_NS_URI
    ns_di = "{%s}" % BPMNDI_NS_URI
    ns_dc = "{%s}" % DC_NS_URI
    ns_diagram = "{%s}" % DI_NS_URI
    ns_bioc = "{%s}" % BIOC_NS_URI
    ns_color = "{%s}" % COLOR_NS_URI

    lane_of, lanes_order = _assign_lanes(wp)

    definitions = ET.Element(f"{ns}definitions", {
        "id": "Definitions_TOBE",
        "targetNamespace": "http://bpmn.io/schema/bpmn",
    })

    collaboration = ET.SubElement(definitions, f"{ns}collaboration", {"id": "Collaboration_TOBE"})
    ET.SubElement(collaboration, f"{ns}participant", {
        "id": "Participant_TOBE",
        "name": wp.process_name or "Process",
        "processRef": "Process_TOBE",
    })

    process_el = ET.SubElement(definitions, f"{ns}process", {"id": "Process_TOBE", "isExecutable": "true"})

    lane_set = ET.SubElement(process_el, f"{ns}laneSet", {"id": "LaneSet_1"})
    lane_elements = {}
    for i, lane_name in enumerate(lanes_order):
        lane_el = ET.SubElement(lane_set, f"{ns}lane", {"id": f"Lane_{i + 1}", "name": lane_name})
        lane_elements[lane_name] = lane_el

    for node_id, tag in wp.node_tags.items():
        ET.SubElement(process_el, f"{ns}{tag}", {"id": node_id, "name": wp.node_names.get(node_id, node_id)})
        lane_name = lane_of.get(node_id, lanes_order[0])
        ET.SubElement(lane_elements[lane_name], f"{ns}flowNodeRef").text = node_id

    flow_counter = 0
    gateways_array = []
    all_flows = []

    for gw_id, gw in wp.gateways.items():
        branches = []
        for target in wp.outgoing.get(gw_id, []):
            condition = gw.branch_conditions.get(target)
            probability = gw.branch_probabilities.get(target)
            flow_counter += 1
            flow_id = f"Flow_{flow_counter}"
            attrs = {"id": flow_id, "sourceRef": gw_id, "targetRef": target}
            if condition:
                attrs["name"] = condition
            ET.SubElement(process_el, f"{ns}sequenceFlow", attrs)
            all_flows.append((flow_id, gw_id, target))

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
            flow_id = f"Flow_{flow_counter}"
            ET.SubElement(process_el, f"{ns}sequenceFlow", {
                "id": flow_id, "sourceRef": node_id, "targetRef": target,
            })
            all_flows.append((flow_id, node_id, target))

    boxes, lane_index, lane_top, lane_height, total_width, total_height = _compute_layout(wp, lane_of, lanes_order)
    lane_boundaries = _lane_boundaries(lanes_order, lane_top, lane_height)

    pool_width = total_width
    pool_height = total_height

    diagram = ET.SubElement(definitions, f"{ns_di}BPMNDiagram", {"id": "BPMNDiagram_TOBE"})
    plane = ET.SubElement(diagram, f"{ns_di}BPMNPlane", {"id": "BPMNPlane_TOBE", "bpmnElement": "Collaboration_TOBE"})

    participant_shape = ET.SubElement(plane, f"{ns_di}BPMNShape", {
        "id": "Participant_TOBE_di",
        "bpmnElement": "Participant_TOBE",
        "isHorizontal": "true",
        f"{ns_bioc}stroke": POOL_STYLE["stroke"],
        f"{ns_bioc}fill": POOL_STYLE["fill"],
        f"{ns_color}background-color": POOL_STYLE["fill"],
        f"{ns_color}border-color": POOL_STYLE["stroke"],
    })
    ET.SubElement(participant_shape, f"{ns_dc}Bounds", {
        "x": "0", "y": "0", "width": str(round(pool_width)), "height": str(round(pool_height)),
    })

    for i, lane_name in enumerate(lanes_order):
        style = PALETTE[i % len(PALETTE)]
        lane_shape = ET.SubElement(plane, f"{ns_di}BPMNShape", {
            "id": f"Lane_{i + 1}_di",
            "bpmnElement": f"Lane_{i + 1}",
            "isHorizontal": "true",
            f"{ns_bioc}stroke": style["stroke"],
            f"{ns_bioc}fill": style["lane_fill"],
            f"{ns_color}background-color": style["lane_fill"],
            f"{ns_color}border-color": style["stroke"],
        })
        ET.SubElement(lane_shape, f"{ns_dc}Bounds", {
            "x": "30", "y": str(round(lane_top[lane_name])),
            "width": str(round(pool_width - 30)), "height": str(round(lane_height[lane_name])),
        })

    for node_id, (x, y, w, h) in boxes.items():
        tag = wp.node_tags[node_id]
        lane_name = lane_of.get(node_id, lanes_order[0])
        li = lane_index[lane_name]
        stroke, fill = _color_for(tag, li)

        attrs = {"id": f"{node_id}_di", "bpmnElement": node_id}
        if stroke:
            attrs[f"{ns_bioc}stroke"] = stroke
            attrs[f"{ns_bioc}fill"] = fill
            attrs[f"{ns_color}background-color"] = fill
            attrs[f"{ns_color}border-color"] = stroke
        if tag in ("exclusiveGateway", "inclusiveGateway", "parallelGateway"):
            attrs["isMarkerVisible"] = "true"

        shape = ET.SubElement(plane, f"{ns_di}BPMNShape", attrs)
        ET.SubElement(shape, f"{ns_dc}Bounds", {
            "x": str(round(x)), "y": str(round(y)), "width": str(round(w)), "height": str(round(h)),
        })

    for flow_id, src, tgt in all_flows:
        if src not in boxes or tgt not in boxes:
            continue
        waypoints = _route_edge(src, tgt, boxes, lane_boundaries)
        edge = ET.SubElement(plane, f"{ns_di}BPMNEdge", {
            "id": f"{flow_id}_di", "bpmnElement": flow_id,
        })
        for wx, wy in waypoints:
            ET.SubElement(edge, f"{ns_diagram}waypoint", {"x": str(round(wx)), "y": str(round(wy))})

    bpmn_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(definitions, encoding="unicode")

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