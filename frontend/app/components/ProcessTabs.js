"use client";

import { useMemo, useState } from "react";
import BpmnViewer from "./BpmnViewer";
import QuantitativeAnalysis from "./QuantitativeAnalysis";
import { generateBpmnXml } from "../lib/bpmnXmlGenerator";

const TABS = ["AS-IS", "TO-BE"];

export default function ProcessTabs({ asIsProcess }) {
  const [activeTab, setActiveTab] = useState("AS-IS");
  const [toBeData, setToBeData] = useState(asIsProcess);
  const [optimizing, setOptimizing] = useState(false);
  const [message, setMessage] = useState(null);

  async function handleOptimize() {
    setOptimizing(true);
    setMessage(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const res = await fetch(`${apiUrl}/optimize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(asIsProcess),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      setToBeData(data);
      setMessage({ type: "success", text: "TO-BE process updated from the optimization engine." });
    } catch {
      setMessage({
        type: "info",
        text: "The optimization backend isn't available yet — showing the AS-IS process here as a placeholder.",
      });
    } finally {
      setOptimizing(false);
    }
  }

  const activeData = activeTab === "AS-IS" ? asIsProcess : toBeData;
  // Some process records (e.g. the newer source schema) don't carry a
  // bpmn_xml diagram — reconstruct one from gateways/process_task so the
  // viewer still has something to render.
  const diagramXml = useMemo(
    () => activeData.bpmn_xml || generateBpmnXml(activeData),
    [activeData]
  );

  return (
    <div className="w-full flex flex-col gap-4">
      <div className="flex items-center gap-2 border-b border-gray-300">
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer ${
              activeTab === tab
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-800"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "TO-BE" && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
            <p className="text-sm text-blue-900">
              Request an optimized redesign of this process from the RL optimization engine.
            </p>
            <button
              type="button"
              onClick={handleOptimize}
              disabled={optimizing}
              className="shrink-0 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 cursor-pointer"
            >
              {optimizing ? "Optimizing…" : "Optimize"}
            </button>
          </div>
          {message && (
            <p className={`text-sm ${message.type === "success" ? "text-green-700" : "text-amber-700"}`}>
              {message.text}
            </p>
          )}
        </div>
      )}

      <h2 className="text-lg font-semibold">{activeData.process_name}</h2>
      <BpmnViewer xml={diagramXml} />
      <QuantitativeAnalysis processData={activeData} />
    </div>
  );
}
