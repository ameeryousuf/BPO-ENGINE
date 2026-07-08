"use client";

import { useEffect, useState } from "react";
import { runFlowAnalysis } from "../lib/flowAnalysis";

function stripHtml(html) {
  return (html || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

function hours(h) {
  if (h == null) return "—";
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} d (${h.toFixed(0)} h)`;
}

function pct(p) {
  if (p == null) return "—";
  return `${(p * 100).toFixed(1)}%`;
}

function money(v) {
  if (v == null) return "—";
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function StatCard({ label, value, sub, tone = "default" }) {
  const toneClasses = {
    default: "border-gray-200 bg-white",
    warn: "border-amber-300 bg-amber-50",
    danger: "border-red-300 bg-red-50",
  };
  return (
    <div className={`rounded-lg border p-4 flex flex-col gap-1 ${toneClasses[tone]}`}>
      <span className="text-xs uppercase tracking-wide text-gray-500">{label}</span>
      <span className="text-xl font-semibold text-gray-900">{value}</span>
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
    </div>
  );
}

function PathChips({ steps }) {
  if (!steps.length) return <span className="text-sm text-gray-400">No tasks on this path.</span>;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {steps.map((s, i) => (
        <div key={s.id} className="flex items-center gap-1.5">
          <span className="rounded-md border border-gray-300 bg-gray-50 px-2 py-1 text-xs text-gray-700">
            {s.name} <span className="text-gray-400">({hours(s.ct)})</span>
          </span>
          {i < steps.length - 1 && <span className="text-gray-300">→</span>}
        </div>
      ))}
    </div>
  );
}

export default function QuantitativeAnalysis({ processData }) {
  // BPMN parsing relies on DOMParser, which only exists in the browser, so
  // the analysis is computed client-side after mount rather than during SSR.
  const [analysis, setAnalysis] = useState(null);

  useEffect(() => {
    try {
      setAnalysis({ ok: true, data: runFlowAnalysis(processData) });
    } catch (err) {
      setAnalysis({ ok: false, error: err.message || String(err) });
    }
  }, [processData]);

  if (!analysis) {
    return <div className="text-sm text-gray-400">Computing quantitative analysis…</div>;
  }

  if (!analysis.ok) {
    return (
      <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700">
        Quantitative analysis failed: {analysis.error}
      </div>
    );
  }

  const a = analysis.data;
  const utilTone = (u) => (u == null ? "default" : u > 0.9 ? "danger" : u > 0.75 ? "warn" : "default");

  return (
    <div className="w-full flex flex-col gap-6">
      <div>
        <h3 className="text-base font-semibold text-gray-900">Quantitative Analysis</h3>
        <p className="text-xs text-gray-500">
          Flow analysis per Dumas et al., <em>Fundamentals of Business Process Management</em> (2nd ed.), Ch. 7.
        </p>
      </div>

      {a.meta.overview && (
        <p className="text-sm text-gray-600 -mt-3">{stripHtml(a.meta.overview)}</p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard label="Expected Cycle Time" value={hours(a.cycleTime.expectedHours)} sub="probability-weighted (Eq. 7.1-7.4)" />
        <StatCard
          label="Cycle Time Efficiency"
          value={a.cycleTime.efficiency != null ? pct(a.cycleTime.efficiency) : "N/A"}
          sub={a.cycleTime.efficiency != null ? "processing time ÷ cycle time" : "no processing-time data recorded"}
        />
        <StatCard label="Expected Cost / Instance" value={money(a.cost.expectedTotal)} sub="labor cost, probability-weighted" />
        <StatCard
          label="Bottleneck Resource"
          value={a.bottleneck ? a.bottleneck.name : "—"}
          sub={a.bottleneck ? `${pct(a.bottleneck.utilization)} utilization` : "no resource data"}
          tone={a.bottleneck ? utilTone(a.bottleneck.utilization) : "default"}
        />
        <StatCard label="Tasks / Gateways" value={`${a.meta.taskCount} / ${a.meta.gatewayCounts.xor + a.meta.gatewayCounts.inclusive + a.meta.gatewayCounts.and}`} sub="from BPMN model" />
      </div>

      {a.meta.endEvents.length > 1 && (
        <div>
          <h4 className="text-sm font-semibold text-gray-800 mb-2">Possible Outcomes</h4>
          <div className="flex flex-wrap gap-2">
            {a.meta.endEvents.map((e) => (
              <span key={e.name} className="rounded-full border border-gray-300 bg-gray-50 px-3 py-1 text-xs text-gray-700">
                {e.name}: <span className="font-medium">{pct(e.probability)}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div>
        <h4 className="text-sm font-semibold text-gray-800 mb-2">Critical Path (worst-case)</h4>
        <PathChips steps={a.criticalPath} />
      </div>

      <div>
        <h4 className="text-sm font-semibold text-gray-800 mb-2">Resource Utilization &amp; Bottlenecks</h4>
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2">Resource</th>
                <th className="px-3 py-2">Load / Instance</th>
                <th className="px-3 py-2">Capacity / Period</th>
                <th className="px-3 py-2">Utilization</th>
              </tr>
            </thead>
            <tbody>
              {a.resources.map((r) => (
                <tr key={r.jobId} className="border-t border-gray-100">
                  <td className="px-3 py-2 font-medium text-gray-800">{r.name}</td>
                  <td className="px-3 py-2 text-gray-600">{hours(r.loadHoursPerInstance)}</td>
                  <td className="px-3 py-2 text-gray-600">{r.capacityPerPeriod ? `${r.capacityPerPeriod} h` : "—"}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        utilTone(r.utilization) === "danger"
                          ? "bg-red-100 text-red-700"
                          : utilTone(r.utilization) === "warn"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-gray-100 text-gray-700"
                      }`}
                    >
                      {pct(r.utilization)}
                    </span>
                  </td>
                </tr>
              ))}
              {a.resources.length === 0 && (
                <tr>
                  <td className="px-3 py-4 text-center text-gray-400" colSpan={4}>
                    No resource/job data found on tasks.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h4 className="text-sm font-semibold text-gray-800 mb-2">Task Breakdown</h4>
        <div className="overflow-x-auto rounded-lg border border-gray-200 max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500 sticky top-0">
              <tr>
                <th className="px-3 py-2">Task</th>
                <th className="px-3 py-2">Duration</th>
                <th className="px-3 py-2">Processing</th>
                <th className="px-3 py-2">Waiting</th>
                <th className="px-3 py-2">Visit Prob.</th>
                <th className="px-3 py-2">Expected Duration</th>
                <th className="px-3 py-2">Cost</th>
                <th className="px-3 py-2">Performers</th>
              </tr>
            </thead>
            <tbody>
              {a.taskBreakdown.map((t) => (
                <tr key={t.id} className="border-t border-gray-100">
                  <td className="px-3 py-2 font-medium text-gray-800">{t.name}</td>
                  <td className="px-3 py-2 text-gray-600">{hours(t.cycleTimeHours)}</td>
                  <td className="px-3 py-2 text-gray-600">{hours(t.processingTimeHours)}</td>
                  <td className="px-3 py-2 text-gray-600">{hours(t.waitingTimeHours)}</td>
                  <td className="px-3 py-2 text-gray-600">{pct(t.visitProbability)}</td>
                  <td className="px-3 py-2 text-gray-600">{hours(t.expectedCycleTimeHours)}</td>
                  <td className="px-3 py-2 text-gray-600">{money(t.cost)}</td>
                  <td className="px-3 py-2 text-gray-600">{t.performers.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {a.notes.length > 0 && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <h4 className="text-sm font-semibold text-blue-900 mb-1">Modeling Assumptions</h4>
          <ul className="list-disc list-inside text-xs text-blue-900/80 space-y-1">
            {a.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
