// Builds the same { nodes, edges } graph shape as bpmnGraph.parseBpmnXml,
// but directly from the native `gateways` + `process_task` arrays instead of
// a BPMN XML document. Used as a fallback for process records (like the
// newer source schema) that don't carry a `bpmn_xml` string.
//
// Graph reconstruction rules, inferred from the schema:
// - process_task[].order gives the default sequential chain of tasks.
// - A gateway with after_task_id/after_gateway_id both null is the entry
//   gateway (wired right after the Start event).
// - A gateway with after_task_id = X is spliced in right after task X,
//   replacing X's default "next task in order" edge.
// - Each branch on a gateway points at exactly one of: target_task_id,
//   target_gateway_id, end_task_id, or end_event_name; the first one present
//   wins. A branch with none of these (just connect_to_end) goes to the
//   shared default End event.
// - A task only gets an implicit "next task in order" edge if the next task
//   isn't itself the explicit target of some gateway branch — otherwise that
//   task is reached solely via the gateway, not via linear order.

const GATEWAY_KIND = {
  EXCLUSIVE: "xor",
  INCLUSIVE: "inclusive",
  PARALLEL: "and",
};

function taskNodeId(taskId) {
  return `Task_${taskId}`;
}

function gatewayNodeId(gatewayId) {
  return `Gateway_${gatewayId}`;
}

export function buildProcessGraphFromJson(processData) {
  const nodes = new Map();
  const edges = [];
  let edgeSeq = 0;
  const nextEdgeId = () => `Flow_gen_${edgeSeq++}`;

  const tasksByOrder = [...(processData?.process_task || [])]
    .filter((pt) => pt?.task_id != null)
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  const gateways = processData?.gateways || [];

  const startId = "StartEvent_1";
  nodes.set(startId, { id: startId, type: "start", name: "Start" });

  const defaultEndId = "EndEvent_default";
  nodes.set(defaultEndId, { id: defaultEndId, type: "end", name: "End" });

  const namedEndIds = new Map();
  function endNodeFor(name) {
    if (!name) return defaultEndId;
    if (namedEndIds.has(name)) return namedEndIds.get(name);
    const id = `EndEvent_${namedEndIds.size + 1}`;
    nodes.set(id, { id, type: "end", name });
    namedEndIds.set(name, id);
    return id;
  }

  for (const pt of tasksByOrder) {
    const id = taskNodeId(pt.task_id);
    nodes.set(id, {
      id,
      type: "task",
      name: pt.task?.task_name || id,
      documentation: "",
    });
  }

  for (const gw of gateways) {
    const id = gatewayNodeId(gw.gateway_pk_id);
    nodes.set(id, {
      id,
      type: "gateway",
      gatewayKind: GATEWAY_KIND[gw.gateway_type] || "xor",
      name: gw.name || `Gateway ${gw.gateway_pk_id}`,
    });
  }

  if (!tasksByOrder.length && !gateways.length) {
    return { nodes, edges };
  }

  const gatewaysByAfterTask = new Map();
  const gatewaysByAfterGateway = new Map();
  let entryGateway = null;
  for (const gw of gateways) {
    if (gw.after_task_id != null) gatewaysByAfterTask.set(gw.after_task_id, gw);
    else if (gw.after_gateway_id != null) gatewaysByAfterGateway.set(gw.after_gateway_id, gw);
    else if (!entryGateway) entryGateway = gw;
  }

  function branchTargetId(branch) {
    if (branch.target_task_id != null) return taskNodeId(branch.target_task_id);
    if (branch.target_gateway_id != null) return gatewayNodeId(branch.target_gateway_id);
    if (branch.end_task_id != null) return taskNodeId(branch.end_task_id);
    if (branch.end_event_name) return endNodeFor(branch.end_event_name);
    return defaultEndId;
  }

  // Start -> entry gateway, or straight to the first task if there's no gateway up front.
  if (entryGateway) {
    edges.push({ id: nextEdgeId(), source: startId, target: gatewayNodeId(entryGateway.gateway_pk_id), name: null });
  } else if (tasksByOrder.length) {
    edges.push({ id: nextEdgeId(), source: startId, target: taskNodeId(tasksByOrder[0].task_id), name: null });
  }

  // Gateway -> gateway chaining for gateways spliced after another gateway.
  for (const [afterGatewayId, gw] of gatewaysByAfterGateway.entries()) {
    const alreadyWired = (gateways.find((g) => g.gateway_pk_id === afterGatewayId)?.branches || []).some(
      (br) => br.target_gateway_id === gw.gateway_pk_id
    );
    if (!alreadyWired) {
      edges.push({ id: nextEdgeId(), source: gatewayNodeId(afterGatewayId), target: gatewayNodeId(gw.gateway_pk_id), name: null });
    }
  }

  // Branch edges out of every gateway.
  for (const gw of gateways) {
    const gwId = gatewayNodeId(gw.gateway_pk_id);
    for (const br of gw.branches || []) {
      edges.push({ id: nextEdgeId(), source: gwId, target: branchTargetId(br), name: br.condition || null });
    }
  }

  // Explicit branch targets don't get a redundant implicit "next in order" edge.
  const explicitTaskTargets = new Set();
  for (const gw of gateways) {
    for (const br of gw.branches || []) {
      if (br.target_task_id != null) explicitTaskTargets.add(br.target_task_id);
    }
  }

  for (let i = 0; i < tasksByOrder.length; i++) {
    const taskId = tasksByOrder[i].task_id;
    const gwAfter = gatewaysByAfterTask.get(taskId);
    if (gwAfter) {
      edges.push({ id: nextEdgeId(), source: taskNodeId(taskId), target: gatewayNodeId(gwAfter.gateway_pk_id), name: null });
      continue;
    }
    const next = tasksByOrder[i + 1];
    if (next && !explicitTaskTargets.has(next.task_id)) {
      edges.push({ id: nextEdgeId(), source: taskNodeId(taskId), target: taskNodeId(next.task_id), name: null });
    } else {
      edges.push({ id: nextEdgeId(), source: taskNodeId(taskId), target: defaultEndId, name: null });
    }
  }

  return { nodes, edges };
}
