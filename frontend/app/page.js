"use client";

import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import { fetchProcess } from "@/lib/api";
import { Fragment, useState } from "react";

const BpmnViewer = dynamic(() => import("../components/BpmnViewer"), { ssr: false });

const fadeUp = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } },
};

const HEURISTIC_DEFINITIONS = {
  "Parallelism": {
    accent: "#1565C0",
    targets: "TIME",
    definition:
      "Run two steps at the same time instead of one after another. Many steps are only done in sequence out of habit or convention, not because one truly depends on the other finishing first.",
    rule:
      "Looks for two neighboring steps where the first leads directly into the second, with nothing else branching in between. Picks the pair that saves the most time by running together, then redraws the process so both steps start at the same moment and the flow only continues once both are finished.",
    effect: "Cuts cycle time. Cost stays the same — the same work still happens, just not one at a time.",
  },
  "Activity Automation": {
    accent: "#B45309",
    targets: "TIME + COST",
    definition:
      "Use technology to do a task faster and more cheaply than a person doing it by hand. Automated steps are quicker, more consistent, and usually cost less per run.",
    rule:
      "Any step that still takes measurable time is a candidate. The system picks whichever qualifying step currently takes the longest, then cuts its working time in half and its waiting time in half too.",
    effect: "Cuts both time and cost, since labor cost is tied to how long a person spends on the step.",
    note: "The 50% reduction is a planning assumption, not a measured figure — real automation savings vary by task.",
  },
  "Activity Elimination": {
    accent: "#2E7D32",
    targets: "TIME + COST",
    definition:
      "Remove a step entirely if it doesn't add real value. Steps that exist only as a leftover habit, or to double-check something nobody is actually accountable for, can often be dropped.",
    rule:
      "A step qualifies if no one is clearly marked as doing the work or answering for the outcome. Among qualifying steps, the system removes the one that currently takes the most time, and reconnects the flow around it.",
    effect: "Removes all the time and cost tied to that step.",
    note: "This is a simplifying proxy for \u201cadds no value\u201d — real value judgments are often more nuanced than ownership alone.",
  },
  "Activity Composition": {
    accent: "#1565C0",
    targets: "TIME",
    definition:
      "Combine two small steps into one. When the same person handles both, merging them saves the hand-off and setup time that happens every time work switches from one step to the next.",
    rule:
      "Two neighboring steps qualify if the same person is mainly responsible for both. The system merges the pair with the largest estimated setup-time saving into a single new step, combining their time and everyone involved.",
    effect: "A modest cut to cycle time from avoiding the repeated hand-off. Cost is largely unchanged — it's the same total work, just done in one motion.",
  },
  "Case-Based Work": {
    accent: "#B45309",
    targets: "TIME",
    definition:
      "Stop letting individual cases sit and wait for a scheduled batch run. Some steps only happen on a fixed weekly or monthly cycle, even though the actual work doesn't need to wait that long.",
    rule:
      "A step qualifies if it has real waiting time and runs on a weekly or monthly schedule. The system picks whichever qualifying step has the most waiting time built up, and cuts it down to a fifth of what it was.",
    effect: "A significant cut to cycle time. Cost is unaffected, since waiting time isn't billed labor in this model.",
  },
  "Empower": {
    accent: "#2E7D32",
    targets: "TIME + COST",
    definition:
      "Let the people doing the work make the decision, instead of pausing every time for a manager's sign-off. Removing an unnecessary approval step means less waiting and less overhead.",
    rule:
      "A step qualifies if someone is currently listed as the approver. The system picks the step where that approver is the most expensive person to keep in the loop, removes the approval role, and reduces waiting time by a fifth.",
    effect: "Cuts both time (less waiting for sign-off) and cost (fewer people billing time to the step).",
  },
  "Numerical Involvement": {
    accent: "#1565C0",
    targets: "TIME",
    definition:
      "Fewer people, fewer hand-offs. When a step loops in more people than it needs — often just to keep them informed — the coordination itself adds delay.",
    rule:
      "A step qualifies if more than two people are attached to it. The system picks the step with the most people involved, removes everyone who is only being kept informed, and trims waiting time slightly for each person removed.",
    effect: "A modest cut to cycle time. Cost stays roughly the same, since informed-only roles typically weren't driving the cost.",
  },
  "Trusted Party": {
    accent: "#B45309",
    targets: "TIME + COST",
    definition:
      "Accept a result someone else already produced instead of redoing the same check yourself. If a trusted outside organization already verified something, re-verifying it from scratch usually just adds delay and cost.",
    rule:
      "A step qualifies if it involves an unusually long wait — a day or more. The system picks whichever qualifying step has the longest wait, cuts its waiting time down to a tenth, and reduces its own working time too.",
    effect: "A large cut to cycle time, plus a meaningful cut to cost from the reduced verification work.",
  },
};

export default function Home() {
  const [processId, setProcessId] = useState("");
  const [goal, setGoal] = useState("both");
  const [episodes, setEpisodes] = useState(300);
  const [includeRedesign, setIncludeRedesign] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const [activeHeuristic, setActiveHeuristic] = useState(null);

  const taskNames = data?.success ? buildTaskNameMap(data.tasks, data.to_be?.tasks) : {};

  async function handleSubmit(e) {
    e.preventDefault();
    if (!processId.trim()) return;

    setLoading(true);
    setError(null);
    setData(null);

    try {
      const result = await fetchProcess(processId.trim(), goal, episodes, includeRedesign);
      if (!result.success) {
        setError(result.message || "Validation failed.");
        setData(result);
      } else {
        setData(result);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong reaching the backend.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#FAFAF9] text-[#12151C]" style={{ fontFamily: "'IBM Plex Sans', sans-serif" }}>
      <div className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-40 -left-40 w-[500px] h-[500px] rounded-full bg-[#1565C0]/10 blur-3xl" />
        <div className="pointer-events-none absolute -top-20 right-0 w-[400px] h-[400px] rounded-full bg-[#B45309]/10 blur-3xl" />

        <div className="relative max-w-5xl mx-auto px-6 pt-20 pb-10">
          <motion.header initial="hidden" animate="visible" variants={fadeUp} className="mb-14 max-w-2xl">
            <p className="text-xs tracking-[0.25em] uppercase text-[#1565C0] mb-3 font-semibold">
              Process Optimization Engine
            </p>
            <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight leading-[1.05]">
              Analyze &amp; redesign
            </h1>
            <p className="text-[#12151C]/55 mt-4 text-[15px] leading-relaxed">
              Enter a process ID to see its current performance and, if a redesign
              is requested, how it could be improved.
            </p>
          </motion.header>

          <motion.form
            onSubmit={handleSubmit}
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            className="bg-white rounded-2xl shadow-[0_2px_20px_rgba(18,21,28,0.06)] border border-black/5 p-6 sm:p-8"
          >
            <div className="grid sm:grid-cols-[1fr_auto_auto] gap-5 items-end">
              <div>
                <label className="block text-xs uppercase tracking-wide text-[#12151C]/45 mb-2 font-medium">
                  Process ID
                </label>
                <input
                  type="text"
                  value={processId}
                  onChange={(e) => setProcessId(e.target.value)}
                  placeholder="1972"
                  className="w-full rounded-xl border border-black/10 bg-[#FAFAF9] px-4 py-3 text-lg focus:outline-none focus:ring-2 focus:ring-[#1565C0]/30 focus:border-[#1565C0] transition-all"
                  style={{ fontFamily: "'IBM Plex Mono', monospace" }}
                />
              </div>

              <div>
                <label className="block text-xs uppercase tracking-wide text-[#12151C]/45 mb-2 font-medium">
                  Goal
                </label>
                <select
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  className="rounded-xl border border-black/10 bg-[#FAFAF9] px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#1565C0]/30 focus:border-[#1565C0] transition-all"
                >
                  <option value="both">Time + Cost</option>
                  <option value="time">Time only</option>
                  <option value="cost">Cost only</option>
                </select>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="bg-[#12151C] hover:cursor-pointer text-white px-7 py-3 rounded-xl text-sm font-medium hover:bg-[#1565C0] transition-colors disabled:opacity-40 shadow-sm"
              >
                {loading ? "Analyzing…" : "Run"}
              </button>
            </div>

            <div className="flex items-center gap-6 mt-5 text-sm text-[#12151C]/55">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeRedesign}
                  onChange={(e) => setIncludeRedesign(e.target.checked)}
                  className="accent-[#1565C0]"
                />
                Include redesign
              </label>
              {includeRedesign && (
                <label className="flex items-center gap-2">
                  Episodes
                  <input
                    type="number"
                    value={episodes}
                    onChange={(e) => setEpisodes(Number(e.target.value))}
                    className="w-20 rounded-lg border border-black/10 bg-[#FAFAF9] px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[#1565C0]/30"
                    style={{ fontFamily: "'IBM Plex Mono', monospace" }}
                  />
                </label>
              )}
            </div>
          </motion.form>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 pb-24">
        {error && (
          <motion.div
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            className="mb-10 bg-red-50 border border-red-200 rounded-xl px-5 py-4 text-sm text-red-700"
          >
            {error}
          </motion.div>
        )}

        {data?.success && data.analysis && (
          <div className="space-y-16 mt-6">
            <Reveal>
              <FlowSummary asIs={data.analysis} toBe={data.to_be} />
            </Reveal>

            <Reveal>
              <Section title="Task Reference" accent="#2E7D32">
                <TaskReference asIsTasks={data.tasks} toBeTasks={data.to_be?.tasks} />
              </Section>
            </Reveal>

            <Reveal>
              <Section title="As-Is" accent="#1565C0">
                <MetricsGrid metrics={data.analysis} />
                <CriticalPaths paths={data.critical_paths} />
              </Section>
            </Reveal>

            {data.to_be && (
              <Reveal>
                <Section title="To-Be" accent="#B45309">
                  <MetricsGrid metrics={data.to_be} />
                  <CriticalPaths paths={data.to_be.critical_paths} />
                </Section>
              </Reveal>
            )}

            {data.overall_improvement && (
              <Reveal>
                <Section title="Overall Improvement" accent="#2E7D32">
                  <div className="grid sm:grid-cols-3 gap-4">
                    <BigStatCard label="Time improvement" value={formatPct(data.overall_improvement.time_improvement_pct)} accent="#1565C0" />
                    <BigStatCard label="Cost improvement" value={formatPct(data.overall_improvement.cost_improvement_pct)} accent="#B45309" />
                    <BigStatCard label="Total reward" value={formatPct(getOverallReward(data.overall_improvement))} accent="#2E7D32" />
                  </div>
                  {data.stop_reason && (
                    <p className="text-sm text-[#12151C]/50 mt-6">
                      Stopped because{" "}
                      <span className="text-[#12151C]/80 font-medium">{formatStopReason(data.stop_reason)}</span>
                    </p>
                  )}
                </Section>
              </Reveal>
            )}

            {data.redesign_trace && (
              <Reveal>
                <Section title="Redesign Trace" accent="#B45309">
                  <p className="text-xs text-[#12151C]/40 mb-3">Click a row to see what this heuristic means.</p>
                  <RedesignTraceTable
                    trace={data.redesign_trace}
                    taskNames={taskNames}
                    onSelectHeuristic={setActiveHeuristic}
                  />
                </Section>
              </Reveal>
            )}

            {data.as_is_bpmn_xml && (
              <Reveal>
                <Section title="As-Is BPMN Diagram" accent="#1565C0">
                  <div className="bg-white rounded-2xl shadow-[0_2px_20px_rgba(18,21,28,0.06)] border border-black/5 p-4">
                    <BpmnViewer xml={data.as_is_bpmn_xml} />
                  </div>
                </Section>
              </Reveal>
            )}

            {data.final_bpmn_xml && (
              <Reveal>
                <Section title="To-Be BPMN Diagram" accent="#B45309">
                  <div className="bg-white rounded-2xl shadow-[0_2px_20px_rgba(18,21,28,0.06)] border border-black/5 p-4">
                    <BpmnViewer xml={data.final_bpmn_xml} />
                  </div>
                </Section>
              </Reveal>
            )}
          </div>
        )}

        {data && !data.success && data.issues && (
          <motion.div
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            className="bg-white rounded-2xl shadow-[0_2px_20px_rgba(18,21,28,0.06)] border border-black/5 p-6"
          >
            <p className="text-sm font-semibold text-red-700 mb-3">Validation issues</p>
            <ul className="space-y-2">
              {data.issues.map((issue, i) => (
                <li key={i} className="text-sm text-red-700/90 bg-red-50 rounded-lg px-3 py-2">
                  {issue}
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </div>

      <HeuristicModal
        heuristic={activeHeuristic}
        onClose={() => setActiveHeuristic(null)}
      />
    </main>
  );
}

function Reveal({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.55, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}

function FlowSummary({ asIs, toBe }) {
  if (!toBe) return null;
  const pctFaster = ((asIs.cycle_time - toBe.cycle_time) / asIs.cycle_time) * 100;

  return (
    <div className="bg-white rounded-2xl shadow-[0_2px_20px_rgba(18,21,28,0.06)] border border-black/5 p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <p className="text-xs uppercase tracking-wide text-[#1565C0] mb-2 font-semibold">As-Is cycle time</p>
          <p className="text-3xl sm:text-4xl font-semibold" style={{ fontFamily: "'IBM Plex Mono', monospace" }}>
            {asIs.cycle_time}
            <span className="text-base font-normal text-[#12151C]/40 ml-2">{asIs.time_unit}</span>
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-wide text-[#B45309] mb-2 font-semibold">To-Be cycle time</p>
          <p className="text-3xl sm:text-4xl font-semibold" style={{ fontFamily: "'IBM Plex Mono', monospace" }}>
            {toBe.cycle_time}
            <span className="text-base font-normal text-[#12151C]/40 ml-2">{toBe.time_unit}</span>
          </p>
        </div>
      </div>

      <div className="relative h-2 bg-[#12151C]/5 rounded-full overflow-hidden">
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-[#1565C0] to-[#B45309]"
          initial={{ width: "0%" }}
          whileInView={{ width: "100%" }}
          viewport={{ once: true }}
          transition={{ duration: 1, ease: "easeInOut", delay: 0.15 }}
        />
      </div>
      <p className="text-center text-sm text-[#2E7D32] font-semibold mt-5">
        {pctFaster.toFixed(1)}% faster
      </p>
    </div>
  );
}

function Section({ title, accent, children }) {
  return (
    <section>
      <div className="flex items-center gap-2.5 mb-6">
        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: accent }} />
        <h2 className="text-xs uppercase tracking-[0.15em] font-semibold text-[#12151C]/60">
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

function MetricsGrid({ metrics }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
      <StatCard label="Cycle time" value={`${metrics.cycle_time}`} unit={metrics.time_unit} />
      <StatCard label="Theoretical cycle time" value={`${metrics.theoretical_cycle_time}`} unit={metrics.time_unit} />
      <StatCard label="Cycle time efficiency" value={`${(metrics.cycle_time_efficiency * 100).toFixed(2)}`} unit="%" />
      <StatCard label="Resource cost" value={metrics.resource_cost.toLocaleString()} unit={metrics.cost_unit} />
      <StatCard label="RACI-weighted cost" value={metrics.raci_cost.toLocaleString()} unit={metrics.cost_unit} />
    </div>
  );
}

function StatCard({ label, value, unit }) {
  return (
    <div className="bg-white rounded-xl shadow-[0_1px_10px_rgba(18,21,28,0.05)] border border-black/5 px-5 py-4">
      <p className="text-xs text-[#12151C]/45 mb-2">{label}</p>
      <p className="text-xl font-semibold" style={{ fontFamily: "'IBM Plex Mono', monospace" }}>
        {value}
        <span className="text-xs font-normal text-[#12151C]/40 ml-1.5">{unit}</span>
      </p>
    </div>
  );
}

function BigStatCard({ label, value, accent }) {
  return (
    <div className="bg-white rounded-2xl shadow-[0_2px_20px_rgba(18,21,28,0.06)] border border-black/5 overflow-hidden">
      <div className="h-1" style={{ backgroundColor: accent }} />
      <div className="px-6 py-5">
        <p className="text-xs uppercase tracking-wide text-[#12151C]/45 mb-2 font-medium">{label}</p>
        <p className="text-3xl font-semibold" style={{ fontFamily: "'IBM Plex Mono', monospace", color: accent }}>
          {value}
        </p>
      </div>
    </div>
  );
}

function CriticalPaths({ paths }) {
  if (!paths || paths.length === 0) return null;

  return (
    <div className="bg-white rounded-2xl shadow-[0_2px_20px_rgba(18,21,28,0.06)] border border-black/5 p-6">
      <p className="text-xs uppercase tracking-wide text-[#12151C]/45 mb-4 font-medium">
        Critical Path Scenarios
      </p>
      <div className="divide-y divide-black/5">
        {paths.map((p) => (
          <div key={p.scenario_id} className="flex items-center justify-between py-3 text-sm gap-4">
            <span className="font-mono text-[#12151C]/60 shrink-0 bg-[#12151C]/5 px-2 py-0.5 rounded">{p.scenario_id}</span>
            <span className="flex-1 font-mono text-xs text-[#12151C]/45 truncate">
              {p.critical_path_task_ids.join(" → ")}
            </span>
            <span className="font-mono font-semibold shrink-0">{p.theoretical_cycle_time} min</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TaskReference({ asIsTasks, toBeTasks }) {
  const [expandedId, setExpandedId] = useState(null);

  if (!asIsTasks?.length) return null;

  const toBeIds = new Set((toBeTasks || []).map((t) => String(t.task_id)));
  const asIsIds = new Set(asIsTasks.map((t) => String(t.task_id)));
  const allIds = Array.from(new Set([...asIsIds, ...toBeIds])).sort((a, b) => Number(a) - Number(b));
  const byId = {};
  (asIsTasks || []).forEach((t) => { byId[String(t.task_id)] = t; });
  (toBeTasks || []).forEach((t) => { byId[String(t.task_id)] = t; });

  return (
    <div className="bg-white rounded-2xl shadow-[0_2px_20px_rgba(18,21,28,0.06)] border border-black/5 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-black/5 bg-[#12151C]/[0.02]">
              <th className="text-left px-6 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">Task ID</th>
              <th className="text-left px-4 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">Task Name</th>
              <th className="text-left px-4 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">Present In</th>
              <th className="text-right px-6 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">RACI</th>
            </tr>
          </thead>
          <tbody>
            {allIds.map((id, i) => {
              const task = byId[id];
              const isOpen = expandedId === id;
              return (
                <Fragment key={id}>
                  <tr
                    onClick={() => setExpandedId(isOpen ? null : id)}
                    className={`border-b border-black/5 last:border-0 cursor-pointer hover:bg-[#1565C0]/[0.04] transition-colors ${i % 2 === 1 ? "bg-[#12151C]/[0.008]" : ""
                      }`}
                  >
                    <td className="px-6 py-3 font-mono text-xs">{id}</td>
                    <td className="px-4 py-3">{task.task_name}</td>
                    <td className="px-4 py-3 text-xs">
                      {asIsIds.has(id) && (
                        <span className="inline-flex items-center gap-1 mr-3 text-[#1565C0]">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#1565C0]" /> As-Is
                        </span>
                      )}
                      {toBeIds.has(id) && (
                        <span className="inline-flex items-center gap-1 text-[#B45309]">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#B45309]" /> To-Be
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-3 text-right text-xs text-[#12151C]/45">
                      {isOpen ? "Hide ▲" : "Show ▼"}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={4} className="px-6 py-4 bg-[#12151C]/[0.015]">
                        <RaciTable raci={task.raci} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RaciTable({ raci }) {
  if (!raci || raci.length === 0) {
    return <p className="text-xs text-[#12151C]/45">No RACI data for this task.</p>;
  }

  const roleLabel = { R: "Responsible", A: "Accountable", C: "Consulted", I: "Informed" };
  const roleColor = { R: "#2E7D32", A: "#B45309", C: "#1565C0", I: "#12151C55" };

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-[#12151C]/45">
          <th className="text-left pb-2 font-medium">Role</th>
          <th className="text-left pb-2 font-medium">Job</th>
          <th className="text-right pb-2 font-medium">Hourly Rate</th>
          <th className="text-right pb-2 font-medium">Time Allocation</th>
        </tr>
      </thead>
      <tbody>
        {raci.map((r, i) => (
          <tr key={i} className="border-t border-black/5">
            <td className="py-2">
              <span
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-medium"
                style={{ backgroundColor: `${roleColor[r.role]}1A`, color: roleColor[r.role] }}
              >
                {r.role} · {roleLabel[r.role] || r.role}
              </span>
            </td>
            <td className="py-2">{r.job_name}</td>
            <td className="py-2 text-right font-mono">
              {r.hourly_rate != null ? `${r.hourly_rate} ${r.currency}` : "—"}
            </td>
            <td className="py-2 text-right font-mono">
              {r.time_allocation_percentage != null ? `${r.time_allocation_percentage}%` : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RedesignTraceTable({ trace, taskNames, onSelectHeuristic }) {
  return (
    <div className="bg-white rounded-2xl shadow-[0_2px_20px_rgba(18,21,28,0.06)] border border-black/5 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-black/5 bg-[#12151C]/[0.02]">
              <th className="text-left px-6 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">Heuristic</th>
              <th className="text-left px-4 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">Status</th>
              <th className="text-left px-4 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">Tasks / Reason</th>
              <th className="text-right px-4 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">Cycle Time</th>
              <th className="text-right px-4 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">Resource Cost</th>
              <th className="text-right px-6 py-3.5 text-xs uppercase tracking-wide text-[#12151C]/45 font-medium">Reward</th>
            </tr>
          </thead>
          <tbody>
            {trace.map((entry, i) => (
              <tr
                key={entry.heuristic}
                onClick={() => onSelectHeuristic(entry.heuristic)}
                className={`border-b border-black/5 last:border-0 hover:bg-[#1565C0]/[0.04] transition-colors cursor-pointer ${i % 2 === 1 ? "bg-[#12151C]/[0.008]" : ""
                  }`}
              >
                <td className="px-6 py-4 font-medium">
                  <span className="underline decoration-dotted decoration-[#12151C]/30 underline-offset-4">
                    {entry.heuristic}
                  </span>
                </td>
                <td className="px-4 py-4">
                  <span
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${entry.implemented
                      ? "bg-[#2E7D32]/10 text-[#2E7D32]"
                      : "bg-[#12151C]/6 text-[#12151C]/45"
                      }`}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ backgroundColor: entry.implemented ? "#2E7D32" : "#12151C55" }}
                    />
                    {entry.implemented ? "Applied" : "Skipped"}
                  </span>
                </td>
                <td className="px-4 py-4 text-[#12151C]/60 max-w-xs">
                  {entry.implemented ? (
                    <span className="font-mono text-xs">
                      {entry.target_task_ids
                        ?.map((id) => `${id} (${taskNames[id] || "unknown"})`)
                        .join(", ")}
                    </span>
                  ) : (
                    <span className="text-xs">{entry.reason}</span>
                  )}
                </td>
                <td className="px-4 py-4 text-right font-mono text-xs">
                  {entry.implemented ? (
                    <>
                      {entry.before?.cycle_time} <span className="text-[#12151C]/30">→</span> {entry.after?.cycle_time}
                    </>
                  ) : (
                    <span className="text-[#12151C]/30">—</span>
                  )}
                </td>
                <td className="px-4 py-4 text-right font-mono text-xs">
                  {entry.implemented ? (
                    <>
                      {entry.before?.resource_cost} <span className="text-[#12151C]/30">→</span> {entry.after?.resource_cost}
                    </>
                  ) : (
                    <span className="text-[#12151C]/30">—</span>
                  )}
                </td>
                <td className="px-6 py-4 text-right">
                  {entry.implemented && entry.reward ? (
                    <span className="font-mono text-xs font-semibold text-[#2E7D32]">
                      +{formatPct(getEntryReward(entry.reward))}
                    </span>
                  ) : (
                    <span className="text-[#12151C]/30 text-xs">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HeuristicModal({ heuristic, onClose }) {
  const info = heuristic ? HEURISTIC_DEFINITIONS[heuristic] : null;

  return (
    <AnimatePresence>
      {info && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-50 flex items-center justify-center px-6"
          onClick={onClose}
        >
          <div className="absolute inset-0 bg-[#12151C]/40 backdrop-blur-sm" />

          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            onClick={(e) => e.stopPropagation()}
            className="relative bg-white rounded-2xl shadow-[0_20px_60px_rgba(18,21,28,0.25)] max-w-lg w-full overflow-hidden"
          >
            <div className="h-1.5" style={{ backgroundColor: info.accent }} />

            <div className="p-8">
              <div className="flex items-start justify-between mb-1">
                <h3 className="text-2xl font-semibold tracking-tight">{heuristic}</h3>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close"
                  className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-[#12151C]/5 text-[#12151C]/50 hover:text-[#12151C] transition-colors shrink-0 -mt-1 -mr-1"
                >
                  ✕
                </button>
              </div>

              <p
                className="text-xs uppercase tracking-wide font-semibold mb-6"
                style={{ color: info.accent }}
              >
                Improves {info.targets}
              </p>

              <p className="text-xs uppercase tracking-wide text-[#12151C]/45 font-medium mb-2">
                What it means
              </p>
              <p className="text-[15px] text-[#12151C] leading-relaxed italic mb-6">
                {info.definition}
              </p>

              <p className="text-xs uppercase tracking-wide text-[#12151C]/45 font-medium mb-2">
                How our system applies it
              </p>
              <p className="text-sm text-[#12151C]/70 leading-relaxed mb-6">
                {info.rule}
              </p>

              <div className="rounded-xl bg-[#2E7D32]/[0.06] px-4 py-3">
                <p className="text-sm font-semibold text-[#2E7D32]">{info.effect}</p>
              </div>

              {info.note && (
                <p className="text-xs text-[#12151C]/45 italic mt-4">{info.note}</p>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function buildTaskNameMap(asIsTasks, toBeTasks) {
  const map = {};
  (asIsTasks || []).forEach((t) => {
    map[String(t.task_id)] = t.task_name;
  });
  (toBeTasks || []).forEach((t) => {
    map[String(t.task_id)] = t.task_name;
  });
  return map;
}

function formatStopReason(reason) {
  const map = {
    no_qualifying_heuristics: "no further improvements were found",
    max_steps_reached: "the maximum number of redesign steps was reached",
    non_positive_q_value: "no remaining option was expected to help enough",
  };
  return map[reason] ?? reason;
}

function formatPct(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}%`;
}

function getEntryReward(reward) {
  if (!reward) return undefined;
  if (typeof reward.reward_percentage === "number") return reward.reward_percentage;
  if (typeof reward.reward === "number") return reward.reward * 100;
  return undefined;
}

function getOverallReward(overall) {
  if (!overall) return undefined;
  if (typeof overall.total_reward === "number") {
    return overall.total_reward < 1 ? overall.total_reward * 100 : overall.total_reward;
  }
  return undefined;
}