"use client";

import { useEffect, useState } from "react";
import ReactBpmn from "react-bpmn";
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn-embedded.css";

export default function BpmnViewer({ xml }) {
  const [error, setError] = useState(null);

  // Clear any previous error as soon as a new diagram comes in; `key={xml}`
  // below forces react-bpmn to mount a fresh viewer instance for it.
  useEffect(() => {
    setError(null);
  }, [xml]);

  return (
    <div className="w-full h-[80vh] border border-gray-300 rounded-lg overflow-hidden">
      {error && (
        <div className="text-red-600 p-4">Failed to render diagram: {error}</div>
      )}
      {!error && xml && (
        <ReactBpmn
          key={xml}
          diagramXML={xml}
          onError={(err) => setError(err.message || String(err))}
        />
      )}
      {!error && !xml && (
        <div className="text-gray-400 p-4">No diagram data available.</div>
      )}
    </div>
  );
}
