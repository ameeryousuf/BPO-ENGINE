"use client";

import { useEffect, useRef, useState } from "react";
import BpmnJS from "bpmn-js/lib/NavigatedViewer";
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn-embedded.css";

export default function BpmnViewer({ xml }) {
    const containerRef = useRef(null);
    const viewerRef = useRef(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!containerRef.current || !xml) return;

        let destroyed = false;
        const viewer = new BpmnJS({ container: containerRef.current });
        viewerRef.current = viewer;

        const importPromise = viewer
            .importXML(xml)
            .then(() => {
                if (destroyed) return;
                viewer.get("canvas").zoom("fit-viewport", "auto");
                setError(null);
            })
            .catch((err) => {
                if (destroyed) return;
                console.error("Failed to render BPMN diagram", err);
                setError("Could not render this diagram.");
            });

        return () => {
            destroyed = true;
            importPromise.finally(() => {
                viewer.destroy();
                if (viewerRef.current === viewer) {
                    viewerRef.current = null;
                }
            });
        };
    }, [xml]);

    function zoomIn() {
        const canvas = viewerRef.current?.get("canvas");
        if (canvas) canvas.zoom(canvas.zoom() * 1.2);
    }

    function zoomOut() {
        const canvas = viewerRef.current?.get("canvas");
        if (canvas) canvas.zoom(canvas.zoom() * 0.8);
    }

    function fitToScreen() {
        viewerRef.current?.get("canvas").zoom("fit-viewport", "auto");
    }

    return (
        <div className="relative">
            <div className="flex items-center gap-3 mb-3">
                <button
                    type="button"
                    onClick={zoomOut}
                    className="w-7 h-7 flex items-center justify-center text-sm border border-[#12151C]/15 rounded-full hover:bg-[#12151C]/5 transition-colors"
                >
                    −
                </button>
                <button
                    type="button"
                    onClick={zoomIn}
                    className="w-7 h-7 flex items-center justify-center text-sm border border-[#12151C]/15 rounded-full hover:bg-[#12151C]/5 transition-colors"
                >
                    +
                </button>
                <button
                    type="button"
                    onClick={fitToScreen}
                    className="text-xs text-[#12151C]/55 hover:text-[#12151C] transition-colors ml-1"
                >
                    Fit to screen
                </button>
            </div>
            <div
                ref={containerRef}
                style={{ height: "500px", width: "100%" }}
                className="border border-[#12151C]/8 rounded-md bg-white"
            />
            {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
        </div>
    );
}