"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { fetchProcess } from "@/lib/api";
const BpmnViewer = dynamic(() => import("../components/BpmnViewer"), { ssr: false });

export default function Home() {
  const [processId, setProcessId] = useState("");
  const [goal, setGoal] = useState("both");
  const [episodes, setEpisodes] = useState(300);
  const [includeRedesign, setIncludeRedesign] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (data) {
      console.log(data.final_bpmn_xml)
    }
  }, [data])

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
    <main
      className="min-h-screen bg-[#FAF8F3] text-[#1A2B4C]"
      style={{ fontFamily: "'IBM Plex Sans', sans-serif" }}
    >
      <div className="max-w-4xl mx-auto px-6 py-16">
        <header className="mb-12">
          <p className="text-xs tracking-[0.2em] uppercase text-[#1565C0] mb-2 font-medium">
            Process Optimization Engine
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">
            Analyze &amp; Redesign
          </h1>
          <p className="text-[#1A2B4C]/60 mt-2 max-w-xl">
            Enter a process ID to see its current performance and, if a redesign
            is requested, how it could be improved.
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          className="bg-white border border-[#1A2B4C]/10 rounded-lg p-6 mb-10 shadow-sm"
        >
          <div className="grid sm:grid-cols-[1fr_auto_auto] gap-4 items-end">
            <div>
              <label className="block text-xs uppercase tracking-wide text-[#1A2B4C]/50 mb-1">
                Process ID
              </label>
              <input
                type="text"
                value={processId}
                onChange={(e) => setProcessId(e.target.value)}
                placeholder="1972"
                className="w-full rounded-md border border-[#1A2B4C]/20 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1565C0] font-mono"
                style={{ fontFamily: "'IBM Plex Mono', monospace" }}
              />
            </div>

            <div>
              <label className="block text-xs uppercase tracking-wide text-[#1A2B4C]/50 mb-1">
                Goal
              </label>
              <select
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                className="rounded-md border border-[#1A2B4C]/20 px-3 py-2 bg-white"
              >
                <option value="both">Time + Cost</option>
                <option value="time">Time only</option>
                <option value="cost">Cost only</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="bg-[#1565C0] text-white hover:shadow-ms shadow-blue-400 hover:cursor-pointer px-5 py-2 rounded-md font-medium hover:bg-[#0F4C9C] transition disabled:opacity-50"
            >
              {loading ? "Analyzing…" : "Run"}
            </button>
          </div>

          <div className="flex items-center gap-6 mt-4 text-sm text-[#1A2B4C]/70">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeRedesign}
                onChange={(e) => setIncludeRedesign(e.target.checked)}
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
                  className="w-20 rounded-md border border-[#1A2B4C]/20 px-2 py-1 font-mono"
                  style={{ fontFamily: "'IBM Plex Mono', monospace" }}
                />
              </label>
            )}
          </div>
        </form>

        {error && (
          <div className="mb-8 rounded-md border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">
            {error}
          </div>
        )}

        {data?.success && data.analysis && (
          <div className="space-y-10">
            <FlowSummary asIs={data.analysis} toBe={data.to_be} />

            <Section title="As-Is" accent="#1565C0">
              <MetricsGrid metrics={data.analysis} />
              <CriticalPaths paths={data.critical_paths} />
            </Section>

            {data.to_be && (
              <Section title="To-Be" accent="#B45309">
                <MetricsGrid metrics={data.to_be} />
                <CriticalPaths paths={data.to_be.critical_paths} />
              </Section>
            )}

            {data.overall_improvement && (
              <Section title="Overall Improvement" accent="#2E7D32">
                <div className="grid sm:grid-cols-3 gap-4">
                  <Stat
                    label="Time improvement"
                    value={formatPct(data.overall_improvement.time_improvement_pct)}
                  />
                  <Stat
                    label="Cost improvement"
                    value={formatPct(data.overall_improvement.cost_improvement_pct)}
                  />
                  <Stat
                    label="Total reward"
                    value={formatPct(getOverallReward(data.overall_improvement))}
                  />
                </div>
                {data.stop_reason && (
                  <p className="text-sm text-[#1A2B4C]/60 mt-4">
                    Stopped because:{" "}
                    <span className="font-medium">{formatStopReason(data.stop_reason)}</span>
                  </p>
                )}
              </Section>
            )}

            {data.redesign_trace && (
              <Section title="Redesign Trace" accent="#B45309">
                <RedesignTrace trace={data.redesign_trace} />
              </Section>
            )}

            {data.as_is_bpmn_xml && (
              <Section title="As-Is BPMN Diagram" accent="#1565C0">
                <BpmnViewer xml={data.as_is_bpmn_xml} />
              </Section>
            )}

            {data.final_bpmn_xml && (
              <Section title="To-Be BPMN Diagram" accent="#B45309">
                <BpmnViewer xml={data.final_bpmn_xml} />
              </Section>
            )}
          </div>
        )}

        {data && !data.success && data.issues && (
          <div className="rounded-md border border-red-200 bg-red-50 p-4">
            <p className="font-medium text-red-700 mb-2">Validation issues</p>
            <ul className="list-disc list-inside text-sm text-red-700 space-y-1">
              {data.issues.map((issue, i) => (
                <li key={i}>{issue}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </main>
  );
}

function FlowSummary({ asIs, toBe }) {
  if (!toBe) return null;

  return (
    <div className="bg-white border border-[#1A2B4C]/10 rounded-lg p-6 shadow-sm">
      <div className="flex items-center justify-between gap-4">
        <FlowNode label="As-Is" value={`${asIs.cycle_time} ${asIs.time_unit}`} color="#1565C0" />
        <div className="flex-1 h-px bg-gradient-to-r from-[#1565C0] to-[#B45309] relative">
          <span className="absolute -top-3 left-1/2 -translate-x-1/2 text-xs text-[#1A2B4C]/50 whitespace-nowrap font-mono">
            {(((asIs.cycle_time - toBe.cycle_time) / asIs.cycle_time) * 100).toFixed(1)}% faster
          </span>
        </div>
        <FlowNode label="To-Be" value={`${toBe.cycle_time} ${toBe.time_unit}`} color="#B45309" />
      </div>
    </div>
  );
}

function FlowNode({ label, value, color }) {
  return (
    <div className="text-center">
      <div className="w-3 h-3 rounded-full mx-auto mb-2" style={{ backgroundColor: color }} />
      <p className="text-xs uppercase tracking-wide text-[#1A2B4C]/50">{label}</p>
      <p className="font-mono font-medium" style={{ fontFamily: "'IBM Plex Mono', monospace" }}>
        {value}
      </p>
    </div>
  );
}

function Section({ title, accent, children }) {
  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: accent }} />
        <h2 className="text-sm uppercase tracking-wide font-medium text-[#1A2B4C]/70">
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

function MetricsGrid({ metrics }) {
  return (
    <div className="grid sm:grid-cols-3 gap-4 mb-6">
      <Stat label="Cycle time" value={`${metrics.cycle_time} ${metrics.time_unit}`} />
      <Stat
        label="Theoretical cycle time"
        value={`${metrics.theoretical_cycle_time} ${metrics.time_unit}`}
      />
      <Stat label="Cycle time efficiency" value={`${(metrics.cycle_time_efficiency * 100).toFixed(2)}%`} />
      <Stat label="Resource cost" value={`${metrics.resource_cost.toLocaleString()} ${metrics.cost_unit}`} />
      <Stat label="RACI-weighted cost" value={`${metrics.raci_cost.toLocaleString()} ${metrics.cost_unit}`} />
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="bg-white border border-[#1A2B4C]/10 rounded-md px-4 py-3">
      <p className="text-xs text-[#1A2B4C]/50 mb-1">{label}</p>
      <p className="text-lg font-medium" style={{ fontFamily: "'IBM Plex Mono', monospace" }}>
        {value}
      </p>
    </div>
  );
}

function CriticalPaths({ paths }) {
  if (!paths || paths.length === 0) return null;

  return (
    <div className="bg-white border border-[#1A2B4C]/10 rounded-md p-4">
      <p className="text-xs uppercase tracking-wide text-[#1A2B4C]/50 mb-3">
        Critical Path Scenarios
      </p>
      <div className="space-y-2">
        {paths.map((p) => (
          <div
            key={p.scenario_id}
            className="flex items-center justify-between text-sm border-b border-[#1A2B4C]/5 pb-2 last:border-0 last:pb-0"
          >
            <span className="font-mono text-[#1A2B4C]/70">{p.scenario_id}</span>
            <span className="flex-1 mx-4 font-mono text-xs text-[#1A2B4C]/50">
              {p.critical_path_task_ids.join(" → ")}
            </span>
            <span className="font-mono font-medium">{p.theoretical_cycle_time} min</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RedesignTrace({ trace }) {
  return (
    <div className="space-y-2">
      {trace.map((entry) => (
        <div key={entry.heuristic} className="bg-white border border-[#1A2B4C]/10 rounded-md p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: entry.implemented ? "#2E7D32" : "#1A2B4C33" }}
              />
              <span className="font-medium">{entry.heuristic}</span>
            </div>
            {entry.implemented && entry.reward && (
              <span className="text-xs font-mono px-2 py-1 rounded bg-[#2E7D32]/10 text-[#2E7D32]">
                +{formatPct(getEntryReward(entry.reward))}
              </span>
            )}
          </div>

          {entry.implemented ? (
            <div className="mt-2 text-sm text-[#1A2B4C]/70 grid sm:grid-cols-2 gap-2">
              <p>
                Tasks: <span className="font-mono">{entry.target_task_ids?.join(", ")}</span>
              </p>
              <p>
                Cycle time: {entry.before?.cycle_time} → {entry.after?.cycle_time} min
              </p>
              <p>
                Resource cost: {entry.before?.resource_cost} → {entry.after?.resource_cost}
              </p>
            </div>
          ) : (
            <p className="mt-2 text-sm text-[#1A2B4C]/60">{entry.reason}</p>
          )}
        </div>
      ))}
    </div>
  );
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
    return overall.total_reward < 1
      ? overall.total_reward * 100
      : overall.total_reward;
  }
  return undefined;
}