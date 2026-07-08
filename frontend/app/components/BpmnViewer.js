"use client";

import { useEffect, useRef, useState } from "react";
import NavigatedViewer from "bpmn-js/lib/NavigatedViewer";
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn-embedded.css";

export default function BpmnViewer({ xml }) {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const viewer = new NavigatedViewer({ container: containerRef.current });
    viewerRef.current = viewer;

    viewer
      .importXML(xml)
      .then(() => {
        viewer.get("canvas").zoom("fit-viewport");
      })
      .catch((err) => setError(err.message));

    return () => viewer.destroy();
  }, [xml]);

  if (error) {
    return <div className="text-red-600">Failed to render diagram: {error}</div>;
  }

  return (
    <div
      ref={containerRef}
      className="w-full h-[80vh] border border-gray-300 rounded-lg"
    />
  );
}
