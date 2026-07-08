// Parses a BPMN 2.0 XML string into a plain graph { nodes, edges }.
// Client-side only (uses DOMParser).

const GATEWAY_TAGS = {
  exclusiveGateway: "xor",
  inclusiveGateway: "inclusive",
  parallelGateway: "and",
  eventBasedGateway: "xor",
  complexGateway: "inclusive",
};

const TASK_TAGS = new Set([
  "task",
  "userTask",
  "serviceTask",
  "scriptTask",
  "manualTask",
  "businessRuleTask",
  "sendTask",
  "receiveTask",
  "callActivity",
  "subProcess",
]);

// Derived from tagName (e.g. "bpmn:task" -> "task") rather than the
// `localName` DOM property, since namespace-prefix stripping on `localName`
// is inconsistent across parser implementations for XML documents.
function localName(el) {
  return el.tagName.split(":").pop();
}

// Namespace-wildcard lookups (getElementsByTagNameNS("*", ...)) are not
// reliably implemented across DOM/XML parser implementations, so we find
// elements by walking the tree and matching on local name instead.
function findFirstByLocalName(root, name) {
  const stack = [...root.children];
  while (stack.length) {
    const el = stack.shift();
    if (localName(el) === name) return el;
    stack.push(...el.children);
  }
  return null;
}

export function parseBpmnXml(xml) {
  const doc = new DOMParser().parseFromString(xml, "text/xml");

  const nodes = new Map();
  const edges = [];

  const processEl = findFirstByLocalName(doc.documentElement, "process");
  if (!processEl) return { nodes, edges };

  for (const el of Array.from(processEl.children)) {
    const tag = localName(el);
    const id = el.getAttribute("id");
    if (!id) continue;

    if (tag === "startEvent") {
      nodes.set(id, { id, type: "start", name: el.getAttribute("name") || "Start" });
    } else if (tag === "endEvent") {
      nodes.set(id, { id, type: "end", name: el.getAttribute("name") || "End" });
    } else if (TASK_TAGS.has(tag)) {
      const docEl = findFirstByLocalName(el, "documentation");
      nodes.set(id, {
        id,
        type: "task",
        name: el.getAttribute("name") || id,
        documentation: docEl ? docEl.textContent : "",
      });
    } else if (GATEWAY_TAGS[tag]) {
      nodes.set(id, {
        id,
        type: "gateway",
        gatewayKind: GATEWAY_TAGS[tag],
        name: el.getAttribute("name") || tag,
      });
    } else if (tag === "sequenceFlow") {
      edges.push({
        id,
        source: el.getAttribute("sourceRef"),
        target: el.getAttribute("targetRef"),
        name: el.getAttribute("name") || null,
      });
    }
  }

  return { nodes, edges };
}
