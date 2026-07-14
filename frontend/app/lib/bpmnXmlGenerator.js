// Synthesizes a minimal, valid BPMN 2.0 XML document (with diagram layout)
// from the JSON-derived process graph, for process records that don't carry
// a `bpmn_xml` string of their own. This lets the BPMN viewer render
// *something* faithful to the recorded gateways/tasks instead of failing to
// import a null document.

import { buildProcessGraphFromJson } from "./processGraph";

const NODE_SIZE = {
  start: { w: 36, h: 36 },
  end: { w: 36, h: 36 },
  gateway: { w: 50, h: 50 },
  task: { w: 150, h: 80 },
};

const GATEWAY_TAG = {
  xor: "exclusiveGateway",
  inclusive: "inclusiveGateway",
  and: "parallelGateway",
};

const COLUMN_GAP = 110;
const ROW_GAP = 40;
const MARGIN = 60;

function topoLevels(nodes, edges) {
  const out = new Map();
  const inn = new Map();
  for (const id of nodes.keys()) {
    out.set(id, []);
    inn.set(id, []);
  }
  for (const e of edges) {
    if (out.has(e.source) && inn.has(e.target)) {
      out.get(e.source).push(e);
      inn.get(e.target).push(e);
    }
  }

  const indeg = new Map();
  for (const id of nodes.keys()) indeg.set(id, inn.get(id).length);
  const queue = [...nodes.keys()].filter((id) => indeg.get(id) === 0);
  const order = [];
  const seen = new Set();
  while (queue.length) {
    const id = queue.shift();
    if (seen.has(id)) continue;
    seen.add(id);
    order.push(id);
    for (const e of out.get(id)) {
      indeg.set(e.target, indeg.get(e.target) - 1);
      if (indeg.get(e.target) <= 0 && !seen.has(e.target)) queue.push(e.target);
    }
  }
  // Disconnected/cyclic leftovers still need a position.
  for (const id of nodes.keys()) if (!seen.has(id)) order.push(id);

  const level = new Map();
  for (const id of order) {
    const preds = inn.get(id) || [];
    level.set(id, preds.length ? Math.max(...preds.map((e) => level.get(e.source) ?? 0)) + 1 : 0);
  }
  return level;
}

function layout(nodes, edges) {
  const level = topoLevels(nodes, edges);
  const byLevel = new Map();
  for (const [id, node] of nodes.entries()) {
    const l = level.get(id) ?? 0;
    if (!byLevel.has(l)) byLevel.set(l, []);
    byLevel.get(l).push(id);
  }

  const positions = new Map();
  let x = MARGIN;
  const maxLevel = Math.max(0, ...byLevel.keys());
  for (let l = 0; l <= maxLevel; l++) {
    const ids = byLevel.get(l) || [];
    let y = MARGIN;
    let colWidth = 0;
    for (const id of ids) {
      const size = NODE_SIZE[nodes.get(id).type] || NODE_SIZE.task;
      positions.set(id, { x, y, w: size.w, h: size.h });
      y += size.h + ROW_GAP;
      colWidth = Math.max(colWidth, size.w);
    }
    x += colWidth + COLUMN_GAP;
  }
  return positions;
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const ELEMENT_TAG = {
  start: () => "startEvent",
  end: () => "endEvent",
  task: () => "task",
  gateway: (node) => GATEWAY_TAG[node.gatewayKind] || "exclusiveGateway",
};

/** Returns a self-contained BPMN 2.0 XML string, or null if there's nothing to draw. */
export function generateBpmnXml(processData) {
  const { nodes, edges } = buildProcessGraphFromJson(processData);
  if (!nodes.size) return null;

  const positions = layout(nodes, edges);
  const processId = `Process_${processData?.process_id ?? "generated"}`;

  const flowElements = [];
  const shapes = [];
  const diEdges = [];

  for (const [id, node] of nodes.entries()) {
    const tag = ELEMENT_TAG[node.type](node);
    flowElements.push(`<bpmn:${tag} id="${id}" name="${esc(node.name)}" />`);
    const pos = positions.get(id);
    shapes.push(
      `<bpmndi:BPMNShape id="${id}_di" bpmnElement="${id}"><dc:Bounds x="${pos.x}" y="${pos.y}" width="${pos.w}" height="${pos.h}" /></bpmndi:BPMNShape>`
    );
  }

  for (const e of edges) {
    const attrs = `id="${e.id}" sourceRef="${e.source}" targetRef="${e.target}"${e.name ? ` name="${esc(e.name)}"` : ""}`;
    flowElements.push(`<bpmn:sequenceFlow ${attrs} />`);
    const src = positions.get(e.source);
    const tgt = positions.get(e.target);
    if (src && tgt) {
      const x1 = src.x + src.w;
      const y1 = src.y + src.h / 2;
      const x2 = tgt.x;
      const y2 = tgt.y + tgt.h / 2;
      diEdges.push(
        `<bpmndi:BPMNEdge id="${e.id}_di" bpmnElement="${e.id}"><di:waypoint x="${x1}" y="${y1}" /><di:waypoint x="${x2}" y="${y2}" /></bpmndi:BPMNEdge>`
      );
    }
  }

  return `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definitions_generated" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="${processId}" name="${esc(processData?.process_name)}" isExecutable="false">
    ${flowElements.join("\n    ")}
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_generated">
    <bpmndi:BPMNPlane id="BPMNPlane_generated" bpmnElement="${processId}">
      ${shapes.join("\n      ")}
      ${diEdges.join("\n      ")}
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;
}
