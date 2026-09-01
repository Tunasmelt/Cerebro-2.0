"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/api";
import { clusterColor } from "@/lib/graph/clusterColor";
import type { ChunkSatellite, GraphEdge, GraphNode } from "@/lib/graph/types";
import { createClient } from "@/lib/supabase/client";
import GraphCanvas from "./GraphCanvas";
import styles from "./graph.module.css";

export default function GraphPage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [satellites, setSatellites] = useState<ChunkSatellite[]>([]);
  const [legendOpen, setLegendOpen] = useState(true);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) {
        router.replace("/signin");
        return;
      }
      setChecking(false);
    });
  }, [router]);

  useEffect(() => {
    if (checking) return;
    (async () => {
      const [nodesRes, edgesRes] = await Promise.all([
        authedFetch("/api/graph/nodes"),
        authedFetch("/api/graph/edges"),
      ]);
      const nodesBody = await nodesRes.json();
      const edgesBody = await edgesRes.json();
      setNodes(nodesBody.nodes ?? []);
      setEdges(edgesBody.edges ?? []);
    })();
  }, [checking]);

  const handleNodeClick = useCallback(
    (nodeId: string | null) => {
      if (nodeId === null) {
        setSelectedNodeId(null);
        setSatellites([]);
        return;
      }
      if (nodeId === selectedNodeId) {
        // Second click on the same node — collapse.
        setSelectedNodeId(null);
        setSatellites([]);
        return;
      }
      setSelectedNodeId(nodeId);
      setSatellites([]);
      authedFetch(`/api/graph/nodes/${nodeId}/chunks`)
        .then((res) => res.json())
        .then((body) => setSatellites(body.chunks ?? []));
    },
    [selectedNodeId]
  );

  if (checking) return null;

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;

  return (
    <div className={styles.page}>
      <div className={styles.canvasWrap}>
        <GraphCanvas
          nodes={nodes}
          edges={edges}
          selectedNodeId={selectedNodeId}
          satellites={satellites}
          onNodeClick={handleNodeClick}
        />
      </div>

      {nodes.length === 0 && (
        <div className={styles.emptyState}>
          No documents yet — upload something to see it here.
        </div>
      )}

      {selectedNode && (
        <div className={styles.sidePanel}>
          <button
            className={styles.closeButton}
            onClick={() => {
              setSelectedNodeId(null);
              setSatellites([]);
            }}
            aria-label="Close"
          >
            ×
          </button>
          <h2 className={styles.sidePanelTitle}>{selectedNode.title}</h2>
          {satellites.length === 0 && (
            <p className={styles.chunkItem}>No chunks yet.</p>
          )}
          {satellites.map((chunk) => (
            <p key={chunk.id} className={styles.chunkItem}>
              {chunk.content.length > 220
                ? `${chunk.content.slice(0, 220)}…`
                : chunk.content}
            </p>
          ))}
        </div>
      )}

      {legendOpen && (
        <div className={styles.legend}>
          <div>node color = cluster</div>
          <div style={{ marginTop: 4 }}>
            <span style={{ color: clusterColor("x") }}>●</span> clustered
            {"  "}
            <span style={{ color: clusterColor(null) }}>●</span> not yet clustered
          </div>
          <button
            onClick={() => setLegendOpen(false)}
            style={{
              marginTop: 6,
              background: "none",
              border: "none",
              color: "#a1a1aa",
              cursor: "pointer",
              fontSize: 11,
              padding: 0,
            }}
          >
            dismiss
          </button>
        </div>
      )}
    </div>
  );
}
