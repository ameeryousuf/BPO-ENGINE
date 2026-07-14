// Quantitative Process Analysis engine.
//
// Implements the Flow Analysis theory from Dumas, La Rosa, Mendling & Reijers,
// "Fundamentals of Business Process Management" (2nd ed.), Chapter 7:
//   - Cycle time via sequence / XOR-block / AND-block / rework-block composition
//     (Eqs. 7.1-7.4), generalized with an expected-value (probability-weighted)
//     formulation so it also supports processes with multiple end events.
//   - Cycle Time Efficiency = TCT / CT (Eq. 7.5), when processing-time data exists.
//   - Little's Law context (arrival rate / WIP) is not computable from a single
//     snapshot, so we surface capacity & utilization instead (Eqs. 7.7-7.8).
//   - Flow analysis for cost (Section 7.1.6): cost is always additive in
//     expectation, so it uses the same probability-weighted sum regardless of
//     gateway type.
//
// Key modeling assumption (flagged to the user in `notes`): branching
// probabilities are not present in the source data, so each XOR/inclusive
// gateway branch is assumed equally likely. Swap in real probabilities
// (e.g. from event-log mining) by extending `edge.name`/a probability field
// on the sequence flow.

import { parseBpmnXml } from "./bpmnGraph";
import { buildProcessGraphFromJson } from "./processGraph";

// Prefer the authored BPMN diagram when present; fall back to reconstructing
// the graph from `gateways` + `process_task` for records (like the newer
// source schema) that don't carry a `bpmn_xml` string.
function resolveGraph(processData) {
  if (processData?.bpmn_xml) return parseBpmnXml(processData.bpmn_xml);
  return buildProcessGraphFromJson(processData);
}

function minutesToHours(min) {
  return (Number(min) || 0) / 60;
}

function buildTaskDataMap(processData) {
  const byTaskId = new Map();
  for (const pt of processData.process_task || []) {
    if (pt.task) byTaskId.set(String(pt.task.task_id), pt);
  }
  return byTaskId;
}

function computeTaskMetrics(task) {
  const ct = minutesToHours(task.expected_process_time);
  // processing_time (like expected_process_time/expected_waiting_time) is
  // recorded in minutes. A task with no recorded processing time (0 or
  // absent) is treated as "not measured" rather than instantaneous, so it's
  // excluded from Theoretical Cycle Time / Cycle Time Efficiency instead of
  // silently making the process look 0% efficient.
  const rawPt = Number(task.processing_time);
  const processingHours = rawPt > 0 ? minutesToHours(rawPt) : null;
  const waitingHours = task.expected_waiting_time != null ? minutesToHours(task.expected_waiting_time) : null;

  let cost = 0;
  const loads = new Map(); // job_id -> hours
  const resources = new Map(); // job_id -> job info

  for (const jt of task.jobTasks || []) {
    const pct = jt.time_allocation_percentage != null ? Number(jt.time_allocation_percentage) / 100 : 1;
    const hours = ct * pct;
    const job = jt.job;
    if (job) {
      cost += (Number(job.hourlyRate) || 0) * hours;
      loads.set(job.job_id, (loads.get(job.job_id) || 0) + hours);
      resources.set(job.job_id, job);
    }
  }

  return { ct, pt: processingHours, waiting: waitingHours, cost, loads, resources };
}

function buildAdjacency(nodes, edges) {
  const out = new Map();
  const inn = new Map();
  for (const id of nodes.keys()) {
    out.set(id, []);
    inn.set(id, []);
  }
  for (const edge of edges) {
    if (!out.has(edge.source) || !inn.has(edge.target)) continue;
    out.get(edge.source).push(edge);
    inn.get(edge.target).push(edge);
  }
  return { out, inn };
}

function findBackEdgeIds(roots, out) {
  const state = new Map();
  const backEdges = new Set();

  for (const root of roots) {
    if (state.get(root)) continue;
    const stack = [{ node: root, i: 0 }];
    state.set(root, 1);
    while (stack.length) {
      const frame = stack[stack.length - 1];
      const outs = out.get(frame.node) || [];
      if (frame.i < outs.length) {
        const edge = outs[frame.i++];
        const s = state.get(edge.target);
        if (s === 1) {
          backEdges.add(edge.id);
        } else if (!s) {
          state.set(edge.target, 1);
          stack.push({ node: edge.target, i: 0 });
        }
      } else {
        state.set(frame.node, 2);
        stack.pop();
      }
    }
  }
  return backEdges;
}

function topoSort(nodeIds, out, inn) {
  const indeg = new Map();
  for (const id of nodeIds) indeg.set(id, (inn.get(id) || []).length);
  const queue = nodeIds.filter((id) => indeg.get(id) === 0);
  const order = [];
  while (queue.length) {
    const id = queue.shift();
    order.push(id);
    for (const edge of out.get(id) || []) {
      indeg.set(edge.target, indeg.get(edge.target) - 1);
      if (indeg.get(edge.target) === 0) queue.push(edge.target);
    }
  }
  return order;
}

function isAndGateway(node) {
  return node && node.type === "gateway" && node.gatewayKind === "and";
}

function isDecisionGateway(node) {
  return node && node.type === "gateway" && (node.gatewayKind === "xor" || node.gatewayKind === "inclusive");
}

/**
 * Computes, for every node, the probability that a given process instance
 * visits it (P(node)), using the forward (loop-free) graph.
 * - Decision gateways (XOR/inclusive) split probability equally across branches
 *   (documented assumption: no branching probabilities in source data).
 * - AND gateways pass probability through unchanged on every branch.
 * - AND-joins take the max of incoming probabilities (synchronization, not
 *   alternative paths) to avoid double counting.
 * - Any other join (merge of alternative paths) sums incoming probabilities.
 */
function computeVisitProbabilities(nodes, forwardOut, forwardInn, order) {
  const prob = new Map();
  const roots = order.filter((id) => (forwardInn.get(id) || []).length === 0);
  for (const id of roots) prob.set(id, 1);

  for (const id of order) {
    const node = nodes.get(id);
    const incoming = forwardInn.get(id) || [];
    if (incoming.length > 0) {
      const contributions = incoming.map((edge) => {
        const srcNode = nodes.get(edge.source);
        const srcOut = forwardOut.get(edge.source) || [];
        const srcProb = prob.get(edge.source) || 0;
        const edgeProb = isAndGateway(srcNode) ? 1 : 1 / Math.max(srcOut.length, 1);
        return srcProb * edgeProb;
      });
      prob.set(id, isAndGateway(node) && incoming.length > 1 ? Math.max(...contributions) : contributions.reduce((a, b) => a + b, 0));
    } else if (!prob.has(id)) {
      prob.set(id, 0);
    }
  }
  return prob;
}

/** Detects rework loops (back edges) and returns, per node, a multiplier
 * (1/(1-r)) representing the expected number of extra visits due to rework
 * (Eq. 7.4). Nodes outside any loop get a multiplier of 1. */
function computeLoopMultipliers(nodes, forwardOut, backEdgesBySource, edgesById) {
  const multiplier = new Map();
  for (const id of nodes.keys()) multiplier.set(id, 1);

  const allOutEdgesOf = (id) => [...edgesById.values()].filter((e) => e.source === id);

  for (const [exitId, backEdgeIds] of backEdgesBySource.entries()) {
    const totalOut = allOutEdgesOf(exitId).length;
    const r = totalOut > 0 ? backEdgeIds.length / totalOut : 0;
    if (r >= 1) continue; // guard against degenerate/unstable loop
    const factor = 1 / (1 - r);

    for (const backEdgeId of backEdgeIds) {
      const entryId = edgesById.get(backEdgeId).target;
      const bodyNodes = findNodesBetween(entryId, exitId, forwardOut);
      for (const nodeId of bodyNodes) {
        multiplier.set(nodeId, multiplier.get(nodeId) * factor);
      }
    }
  }
  return { multiplier };
}

function findNodesBetween(fromId, toId, forwardOut) {
  // BFS forward from `fromId`, collecting nodes that can still reach `toId`.
  const reachableFromEntry = new Set();
  const queue = [fromId];
  reachableFromEntry.add(fromId);
  while (queue.length) {
    const id = queue.shift();
    if (id === toId) continue;
    for (const edge of forwardOut.get(id) || []) {
      if (!reachableFromEntry.has(edge.target)) {
        reachableFromEntry.add(edge.target);
        queue.push(edge.target);
      }
    }
  }
  return reachableFromEntry;
}

/** Longest path (by cycle time) through the forward graph, from any root to
 * any sink — a generalization of the Critical Path Method (Section 7.1.3) to
 * graphs with decision gateways and multiple end events. */
function longestPath(nodes, order, forwardInn, ctOf) {
  const best = new Map();
  const parent = new Map();
  for (const id of order) {
    const incoming = forwardInn.get(id) || [];
    if (incoming.length === 0) {
      best.set(id, ctOf(id));
      parent.set(id, null);
    } else {
      let bestVal = -Infinity;
      let bestParent = null;
      for (const edge of incoming) {
        const val = (best.get(edge.source) || 0);
        if (val > bestVal) {
          bestVal = val;
          bestParent = edge.source;
        }
      }
      best.set(id, bestVal + ctOf(id));
      parent.set(id, bestParent);
    }
  }

  let endId = null;
  let endVal = -Infinity;
  for (const id of order) {
    if (nodes.get(id).type === "end" && (best.get(id) || 0) > endVal) {
      endVal = best.get(id);
      endId = id;
    }
  }
  if (endId == null) return { path: [], total: 0 };

  const path = [];
  let cur = endId;
  while (cur != null) {
    path.unshift(cur);
    cur = parent.get(cur);
  }
  return { path, total: endVal };
}

/** Detects clean (non-nested) AND fork/join blocks and returns a correction
 * (delta) to subtract-sum/add-max, per Eq. 7.3. */
function computeAndBlockCorrection(nodes, forwardOut, forwardInn, visitProb, ctOf) {
  let correction = 0;
  const resolvedGateways = new Set();
  const caveats = [];

  for (const [id, node] of nodes.entries()) {
    if (!isAndGateway(node)) continue;
    const outs = forwardOut.get(id) || [];
    if (outs.length < 2 || resolvedGateways.has(id)) continue;

    const branchInfo = outs.map((edge) => walkSimpleChain(edge.target, nodes, forwardOut, forwardInn));
    const joinTargets = new Set(branchInfo.map((b) => b.joinId));
    if (joinTargets.size !== 1) continue;
    const joinId = [...joinTargets][0];
    const joinNode = nodes.get(joinId);
    if (!isAndGateway(joinNode)) continue;
    if ((forwardInn.get(joinId) || []).length !== outs.length) continue;
    if (branchInfo.some((b) => b.hasNestedGateway)) {
      caveats.push("Nested parallel (AND) structure detected; its contribution to cycle time may be approximate.");
    }

    const pSplit = visitProb.get(id) || 0;
    if (pSplit === 0) continue;

    const branchTimes = branchInfo.map((b) => b.taskIds.reduce((sum, tId) => sum + (visitProb.get(tId) || 0) * ctOf(tId), 0) / pSplit);
    const sumBranches = branchTimes.reduce((a, b) => a + b, 0);
    const maxBranches = Math.max(...branchTimes, 0);
    correction += (maxBranches - sumBranches) * pSplit;
    resolvedGateways.add(id);
  }

  return { correction, caveats };
}

function walkSimpleChain(startId, nodes, forwardOut, forwardInn) {
  const taskIds = [];
  let cur = startId;
  let hasNestedGateway = false;
  const guard = new Set();
  while (cur != null && !guard.has(cur)) {
    guard.add(cur);
    const node = nodes.get(cur);
    if (!node) break;
    if (node.type === "task") taskIds.push(cur);
    if (node.type === "gateway" && !isAndGateway(node)) hasNestedGateway = true;
    const outs = forwardOut.get(cur) || [];
    const ins = forwardInn.get(cur) || [];
    if (isAndGateway(node) && ins.length === 1 && outs.length > 1) {
      hasNestedGateway = true; // nested AND split, not handled at this level
    }
    if (outs.length !== 1) return { joinId: cur, taskIds, hasNestedGateway };
    cur = outs[0].target;
  }
  return { joinId: cur, taskIds, hasNestedGateway };
}

function modeOf(values) {
  const counts = new Map();
  for (const v of values) counts.set(v, (counts.get(v) || 0) + 1);
  let best = null;
  let bestCount = 0;
  for (const [v, c] of counts.entries()) {
    if (c > bestCount) {
      best = v;
      bestCount = c;
    }
  }
  return best;
}

export function runFlowAnalysis(processData) {
  const notes = [];
  const { nodes, edges } = resolveGraph(processData);
  const taskDataById = buildTaskDataMap(processData);

  const taskMetrics = new Map(); // nodeId -> {ct, pt, cost, loads, resources}
  const resourceRegistry = new Map(); // job_id -> job info

  for (const [nodeId, node] of nodes.entries()) {
    if (node.type !== "task") continue;
    const match = nodeId.match(/(\d+)$/);
    const taskId = match ? match[1] : null;
    const pt = taskId ? taskDataById.get(taskId) : null;
    if (!pt) {
      taskMetrics.set(nodeId, { ct: 0, pt: null, cost: 0, loads: new Map(), resources: new Map() });
      continue;
    }
    const metrics = computeTaskMetrics(pt.task);
    taskMetrics.set(nodeId, metrics);
    for (const [jobId, job] of metrics.resources.entries()) resourceRegistry.set(jobId, job);
  }

  const { out, inn } = buildAdjacency(nodes, edges);
  const edgesById = new Map(edges.map((e) => [e.id, e]));
  const roots = [...nodes.entries()].filter(([, n]) => n.type === "start").map(([id]) => id);
  const effectiveRoots = roots.length ? roots : [...nodes.keys()].filter((id) => (inn.get(id) || []).length === 0);

  const backEdgeIds = findBackEdgeIds(effectiveRoots, out);
  const forwardEdges = edges.filter((e) => !backEdgeIds.has(e.id));
  const { out: forwardOut, inn: forwardInn } = buildAdjacency(nodes, forwardEdges);

  if (backEdgeIds.size > 0) {
    notes.push(
      `${backEdgeIds.size} rework/loop connection(s) detected in the model. A default equal-split rework probability was assumed since none is recorded in the source data.`
    );
  }

  const order = topoSort([...nodes.keys()], forwardOut, forwardInn);
  const visitProb = computeVisitProbabilities(nodes, forwardOut, forwardInn, order);

  // Loop multipliers (Eq. 7.4), applied on top of the single-pass probability.
  const backEdgesBySource = new Map();
  for (const id of backEdgeIds) {
    const e = edgesById.get(id);
    if (!backEdgesBySource.has(e.source)) backEdgesBySource.set(e.source, []);
    backEdgesBySource.get(e.source).push(id);
  }
  const { multiplier: loopMultiplier } = computeLoopMultipliers(nodes, forwardOut, backEdgesBySource, edgesById);
  for (const [id, m] of loopMultiplier.entries()) {
    if (m !== 1) visitProb.set(id, (visitProb.get(id) || 0) * m);
  }

  const ctOf = (id) => taskMetrics.get(id)?.ct || 0;
  const costOf = (id) => taskMetrics.get(id)?.cost || 0;

  const taskIds = [...nodes.entries()].filter(([, n]) => n.type === "task").map(([id]) => id);

  // --- Expected Cycle Time (base, via linearity of expectation) ---
  let expectedCycleTime = 0;
  let expectedTCT = 0;
  let hasProcessingTimeData = false;
  let expectedCost = 0;
  const resourceLoadHours = new Map(); // job_id -> hours per instance

  for (const id of taskIds) {
    const p = visitProb.get(id) || 0;
    expectedCycleTime += p * ctOf(id);
    expectedCost += p * costOf(id);
    const metrics = taskMetrics.get(id);
    if (metrics?.pt != null) {
      hasProcessingTimeData = true;
      expectedTCT += p * metrics.pt;
    }
    if (metrics) {
      for (const [jobId, hours] of metrics.loads.entries()) {
        resourceLoadHours.set(jobId, (resourceLoadHours.get(jobId) || 0) + p * hours);
      }
    }
  }

  // --- AND-block correction (Eq. 7.3: max instead of sum for parallel work) ---
  const { correction, caveats } = computeAndBlockCorrection(nodes, forwardOut, forwardInn, visitProb, ctOf);
  const totalExpectedCycleTime = Math.max(0, expectedCycleTime + correction);
  notes.push(...caveats);

  const hasDecisionGateway = [...nodes.values()].some(isDecisionGateway);
  if (hasDecisionGateway) {
    notes.push(
      "No branching probabilities are recorded on gateway flows in the source data, so each decision gateway assumes its outgoing branches are equally likely."
    );
  }

  // --- Critical path (worst-case, Section 7.1.3) ---
  const cp = longestPath(nodes, order, forwardInn, ctOf);
  const criticalPath = cp.path.filter((id) => nodes.get(id).type === "task").map((id) => ({ id, name: nodes.get(id).name, ct: ctOf(id) }));

  // --- Resource utilization & bottleneck (Section 7.1.5) ---
  const frequencyLabels = (processData.process_task || [])
    .map((pt) => pt.task?.frequency_period)
    .filter(Boolean);
  const periodLabel = modeOf(frequencyLabels) || "WEEK";
  notes.push(
    `Resource utilization assumes the process runs once per ${periodLabel.toLowerCase()} (based on task frequency metadata) and that each role/job represents a single resource, since pool size isn't recorded in the source data.`
  );

  const resources = [...resourceRegistry.entries()].map(([jobId, job]) => {
    const loadHoursPerInstance = resourceLoadHours.get(jobId) || 0;
    const capacityPerPeriod = (Number(job.hours_per_day) || 0) * (Number(job.days_per_week) || 0);
    const utilization = capacityPerPeriod > 0 ? loadHoursPerInstance / capacityPerPeriod : null;
    return {
      jobId,
      name: job.name,
      hourlyRate: Number(job.hourlyRate) || 0,
      loadHoursPerInstance,
      capacityPerPeriod,
      utilization,
    };
  }).sort((a, b) => (b.utilization ?? -1) - (a.utilization ?? -1));

  const bottleneck = resources.length ? resources[0] : null;

  // --- Task breakdown table ---
  const taskBreakdown = taskIds.map((id) => {
    const node = nodes.get(id);
    const metrics = taskMetrics.get(id) || {};
    const p = visitProb.get(id) || 0;
    return {
      id,
      name: node.name,
      cycleTimeHours: metrics.ct || 0,
      processingTimeHours: metrics.pt,
      waitingTimeHours: metrics.waiting,
      visitProbability: p,
      expectedCycleTimeHours: p * (metrics.ct || 0),
      cost: metrics.cost || 0,
      expectedCost: p * (metrics.cost || 0),
      performers: [...(metrics.resources?.values() || [])].map((j) => j.name),
    };
  }).sort((a, b) => b.expectedCycleTimeHours - a.expectedCycleTimeHours);

  const cte = hasProcessingTimeData && totalExpectedCycleTime > 0 ? expectedTCT / totalExpectedCycleTime : null;

  const endEvents = [...nodes.values()].filter((n) => n.type === "end").map((n) => ({ name: n.name, probability: visitProb.get(n.id) || 0 }));
  const gatewayCounts = { xor: 0, inclusive: 0, and: 0 };
  for (const n of nodes.values()) if (n.type === "gateway") gatewayCounts[n.gatewayKind] = (gatewayCounts[n.gatewayKind] || 0) + 1;

  return {
    meta: {
      processName: processData.process_name,
      processCode: processData.process_code,
      overview: processData.process_overview,
      companyName: processData.company?.name,
      taskCount: taskIds.length,
      gatewayCounts,
      endEvents,
    },
    cycleTime: {
      expectedHours: totalExpectedCycleTime,
      theoreticalHours: hasProcessingTimeData ? expectedTCT : null,
      efficiency: cte,
      rawSourceCapacityMinutes: processData.capacity_requirement_minutes,
    },
    cost: {
      expectedTotal: expectedCost,
    },
    resources,
    bottleneck,
    criticalPath,
    taskBreakdown,
    notes: [...new Set(notes)],
  };
}
