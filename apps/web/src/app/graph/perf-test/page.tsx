"use client";

import { useMemo, useState } from "react";

import type { ChunkSatellite, GraphEdge, GraphNode } from "@/lib/graph/types";
import GraphCanvas from "../GraphCanvas";

// Stage 2.3's exit criteria: "Render performance holds at the
// 300-document seed scale (frame rate measured, not eyeballed)." A real
// 300-document corpus is expensive/slow to seed just to check frame
// rate, and this harness needs to be reproducible on demand — so it
// generates synthetic nodes/edges client-side (no auth, no backend
// calls) and mounts the exact same GraphCanvas the real graph page
// uses. The measured FPS is rendered as plain text (data-testid
// below) specifically so a real browser test (Playwright) can read the
// actual number, not eyeball the animation.

const DOCUMENT_COUNT = 300;
const CLUSTER_COUNT = 12;

function buildSyntheticGraph(): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const clusterIds = Array.from({ length: CLUSTER_COUNT }, (_, i) => `cluster-${i}`);
  const nodes: GraphNode[] = Array.from({ length: DOCUMENT_COUNT }, (_, i) => {
    const clusterId = clusterIds[i % CLUSTER_COUNT];
    const angle = (i % CLUSTER_COUNT) * ((Math.PI * 2) / CLUSTER_COUNT);
    return {
      id: `doc-${i}`,
      title: `Synthetic document ${i}`,
      cluster_id: clusterId,
      x: Math.cos(angle) * 3,
      y: Math.sin(angle) * 3,
    };
  });

  const edges: GraphEdge[] = [];
  for (let i = 0; i < DOCUMENT_COUNT; i++) {
    for (let rank = 1; rank <= 3; rank++) {
      const neighbor = (i + rank) % DOCUMENT_COUNT;
      edges.push({
        document_id: `doc-${i}`,
        neighbor_document_id: `doc-${neighbor}`,
        distance: rank,
        rank,
      });
    }
  }

  return { nodes, edges };
}

// Deterministic synthetic satellites for doc-0, so a real Playwright
// click-interaction test (Stage 2.3's "clicking a node reliably expands
// the correct chunk set, closes cleanly on a second click") has a known
// expected result to assert against. The real GET .../chunks endpoint
// itself was already verified live with real data in Stage 2.2 — this
// exercises the click/toggle logic this stage actually adds, on the
// exact same GraphCanvas component the real page uses.
const SATELLITES_BY_DOC: Record<string, ChunkSatellite[]> = {
  "doc-0": [
    { id: "sat-1", ordinal: 0, content: "Synthetic chunk one for doc-0.", meta: {} },
    { id: "sat-2", ordinal: 1, content: "Synthetic chunk two for doc-0.", meta: {} },
  ],
};

export default function GraphPerfTestPage() {
  const { nodes, edges } = useMemo(buildSyntheticGraph, []);
  const [fps, setFps] = useState<number | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [doc0Position, setDoc0Position] = useState<{ x: number; y: number } | null>(null);

  function handleNodeClick(nodeId: string | null) {
    if (nodeId === null || nodeId === selectedNodeId) {
      setSelectedNodeId(null);
      return;
    }
    setSelectedNodeId(nodeId);
  }

  const satellites = selectedNodeId ? SATELLITES_BY_DOC[selectedNodeId] ?? [] : [];

  return (
    <div style={{ width: "100vw", height: "100vh", background: "#0a0a0f" }}>
      <div
        data-testid="fps-readout"
        style={{
          position: "absolute",
          top: 12,
          left: 12,
          color: "#f4f4f5",
          fontFamily: "monospace",
          fontSize: 14,
          zIndex: 10,
        }}
      >
        {fps !== null ? `${fps.toFixed(1)} fps` : "measuring…"}
      </div>
      <div
        data-testid="selection-readout"
        style={{
          position: "absolute",
          top: 32,
          left: 12,
          color: "#f4f4f5",
          fontFamily: "monospace",
          fontSize: 14,
          zIndex: 10,
        }}
      >
        selected: {selectedNodeId ?? "none"} ({satellites.length} satellites)
      </div>
      <div
        data-testid="doc0-position"
        style={{ display: "none" }}
      >
        {doc0Position ? `${doc0Position.x},${doc0Position.y}` : ""}
      </div>
      <GraphCanvas
        nodes={nodes}
        edges={edges}
        selectedNodeId={selectedNodeId}
        satellites={satellites}
        onNodeClick={handleNodeClick}
        onFpsSample={setFps}
        onPositionsSample={(positions) => {
          if (positions["doc-0"]) setDoc0Position(positions["doc-0"]);
        }}
      />
    </div>
  );
}
