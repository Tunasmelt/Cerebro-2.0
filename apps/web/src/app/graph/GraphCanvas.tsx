"use client";

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { useEffect, useRef } from "react";

import { clusterColor } from "@/lib/graph/clusterColor";
import type { ChunkSatellite, GraphEdge, GraphNode } from "@/lib/graph/types";

const NODE_RADIUS = 6;
const SATELLITE_RADIUS = 3;
const SATELLITE_ORBIT = 26;
// Server centroid coordinates are small floats (PCA output, typically
// well under ±5) — scaled up so nodes actually spread across the
// canvas instead of clustering in a few pixels at the center.
const POSITION_SCALE = 60;
// Brightening then fading over roughly 2 seconds is the single most
// important animation in the product (see the retrieval-pulse animation
// in Mockups/ui_kits/brain/index.html), so this duration is a
// deliberate design value, not a placeholder.
const PULSE_DURATION_MS = 2000;

type SimNode = SimulationNodeDatum & GraphNode;
type SimLink = SimulationLinkDatum<SimNode>;

/** `key` must change (e.g. incrementing counter) to re-trigger the
 * animation even when `nodeIds` is identical to the previous pulse —
 * e.g. replaying the same past conversation twice in a row. */
export type GraphPulse = { nodeIds: string[]; key: number };

export type GraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  satellites: ChunkSatellite[];
  onNodeClick: (nodeId: string | null) => void;
  /** Stage 2.4 — the real `retrieval` SSE event's document_ids (live)
   * or a past message's resolved retrieved_document_ids (replay). Null
   * when nothing is currently pulsing. */
  pulse?: GraphPulse | null;
  /** Test hook (Stage 2.3's "frame rate measured, not eyeballed" — see
   * graph/perf-test/page.tsx): called every second with the actual
   * measured frames-per-second, not an assumed/estimated number. */
  onFpsSample?: (fps: number) => void;
  /** Test hook: called every second with each node's current on-canvas
   * pixel position, so a real click-interaction test can target a
   * specific node without guessing where physics settled it. */
  onPositionsSample?: (positions: Record<string, { x: number; y: number }>) => void;
};

export default function GraphCanvas({
  nodes,
  edges,
  selectedNodeId,
  satellites,
  onNodeClick,
  pulse,
  onFpsSample,
  onPositionsSample,
}: GraphCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const simNodesRef = useRef<SimNode[]>([]);
  const simulationRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const hoveredIdRef = useRef<string | null>(null);
  const selectedIdRef = useRef<string | null>(selectedNodeId);
  const onNodeClickRef = useRef(onNodeClick);
  const onFpsSampleRef = useRef(onFpsSample);
  const onPositionsSampleRef = useRef(onPositionsSample);
  const pulseRef = useRef<GraphPulse | null | undefined>(pulse);
  const pulseStartRef = useRef<number>(0);
  const lastPulseKeyRef = useRef<number | null>(null);

  useEffect(() => {
    selectedIdRef.current = selectedNodeId;
  }, [selectedNodeId]);
  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);
  useEffect(() => {
    onFpsSampleRef.current = onFpsSample;
  }, [onFpsSample]);
  useEffect(() => {
    onPositionsSampleRef.current = onPositionsSample;
  }, [onPositionsSample]);
  useEffect(() => {
    pulseRef.current = pulse;
    if (pulse && pulse.key !== lastPulseKeyRef.current) {
      pulseStartRef.current = performance.now();
      lastPulseKeyRef.current = pulse.key;
    }
  }, [pulse]);

  // Rebuild the simulation whenever the node/edge set itself changes —
  // not on every selection/satellite change, which would otherwise
  // restart physics and jitter the whole graph just from a click.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const width = canvas.clientWidth;
    const height = canvas.clientHeight;

    const simNodes: SimNode[] = nodes.map((n) => ({
      ...n,
      x: n.x !== null ? n.x * POSITION_SCALE + width / 2 : width / 2 + (Math.random() - 0.5) * 40,
      y: n.y !== null ? n.y * POSITION_SCALE + height / 2 : height / 2 + (Math.random() - 0.5) * 40,
    }));
    const idToNode = new Map(simNodes.map((n) => [n.id, n]));
    const simLinks: SimLink[] = edges
      .filter((e) => idToNode.has(e.document_id) && idToNode.has(e.neighbor_document_id))
      .map((e) => ({ source: e.document_id, target: e.neighbor_document_id }));

    simNodesRef.current = simNodes;

    const simulation = forceSimulation(simNodes)
      .force("charge", forceManyBody().strength(-80))
      .force("link", forceLink<SimNode, SimLink>(simLinks).id((d) => d.id).distance(50))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collide", forceCollide(NODE_RADIUS * 2));

    simulationRef.current = simulation;

    return () => {
      simulation.stop();
    };
  }, [nodes, edges]);

  // Draw + FPS loop — independent of simulation restarts, runs for the
  // lifetime of the component.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let rafId: number;
    let frameCount = 0;
    let lastFpsTime = performance.now();

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = canvas.clientWidth * dpr;
      canvas.height = canvas.clientHeight * dpr;
      ctx.scale(dpr, dpr);
    };
    resize();
    window.addEventListener("resize", resize);

    const draw = () => {
      const now0 = performance.now();
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#0a0a0f";
      ctx.fillRect(0, 0, width, height);

      const simNodes = simNodesRef.current;
      const idToNode = new Map(simNodes.map((n) => [n.id, n]));

      // Edges — faint, brighter when touching the hovered/selected node.
      for (const e of edges) {
        const a = idToNode.get(e.document_id);
        const b = idToNode.get(e.neighbor_document_id);
        if (!a || !b || a.x == null || a.y == null || b.x == null || b.y == null) continue;
        const touchesFocus =
          e.document_id === selectedIdRef.current ||
          e.neighbor_document_id === selectedIdRef.current ||
          e.document_id === hoveredIdRef.current ||
          e.neighbor_document_id === hoveredIdRef.current;
        ctx.strokeStyle = touchesFocus ? "rgba(139,92,246,0.5)" : "rgba(255,255,255,0.06)";
        ctx.lineWidth = touchesFocus ? 1.5 : 1;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }

      // Retrieval pulse — the current pulse's node set, brightening
      // then fading over PULSE_DURATION_MS. Computed once per frame so
      // every pulsing node fades in lockstep.
      const activePulse = pulseRef.current;
      const pulseElapsed = activePulse ? now0 - pulseStartRef.current : Infinity;
      const pulseActive = !!activePulse && pulseElapsed < PULSE_DURATION_MS;
      const pulseIntensity = pulseActive ? 1 - pulseElapsed / PULSE_DURATION_MS : 0;
      const pulsingIds = pulseActive ? new Set(activePulse!.nodeIds) : null;

      // Nodes.
      for (const n of simNodes) {
        if (n.x == null || n.y == null) continue;
        const isFocus = n.id === selectedIdRef.current || n.id === hoveredIdRef.current;
        const isPulsing = pulsingIds?.has(n.id) ?? false;
        const color = clusterColor(n.cluster_id);
        const radius = isPulsing
          ? NODE_RADIUS * (1.4 + 0.6 * pulseIntensity)
          : isFocus
            ? NODE_RADIUS * 1.4
            : NODE_RADIUS;
        ctx.beginPath();
        ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = isPulsing
          ? `rgba(255,255,255,${0.5 + 0.5 * pulseIntensity})`
          : color;
        if (isPulsing) {
          ctx.shadowColor = color;
          ctx.shadowBlur = 8 + 20 * pulseIntensity;
        } else if (isFocus) {
          ctx.shadowColor = color;
          ctx.shadowBlur = 12;
        } else {
          ctx.shadowBlur = 0;
        }
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      // Chunk satellites around the selected node.
      const parent = selectedIdRef.current ? idToNode.get(selectedIdRef.current) : null;
      if (parent && parent.x != null && parent.y != null && satellites.length > 0) {
        satellites.forEach((chunk, i) => {
          const angle = (i / satellites.length) * Math.PI * 2;
          const sx = parent.x! + Math.cos(angle) * SATELLITE_ORBIT;
          const sy = parent.y! + Math.sin(angle) * SATELLITE_ORBIT;
          ctx.beginPath();
          ctx.arc(sx, sy, SATELLITE_RADIUS, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(255,255,255,0.7)";
          ctx.fill();
          ctx.strokeStyle = "rgba(255,255,255,0.15)";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(parent.x!, parent.y!);
          ctx.lineTo(sx, sy);
          ctx.stroke();
        });
      }

      frameCount++;
      if (now0 - lastFpsTime >= 1000) {
        onFpsSampleRef.current?.(frameCount / ((now0 - lastFpsTime) / 1000));
        frameCount = 0;
        lastFpsTime = now0;
        if (onPositionsSampleRef.current) {
          const positions: Record<string, { x: number; y: number }> = {};
          for (const n of simNodes) {
            if (n.x != null && n.y != null) positions[n.id] = { x: n.x, y: n.y };
          }
          onPositionsSampleRef.current(positions);
        }
      }

      rafId = requestAnimationFrame(draw);
    };
    rafId = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
    };
  }, [edges, satellites]);

  function nodeAtPoint(px: number, py: number): SimNode | null {
    const simNodes = simNodesRef.current;
    let nearest: SimNode | null = null;
    let nearestDist = NODE_RADIUS * 2; // click tolerance
    for (const n of simNodes) {
      if (n.x == null || n.y == null) continue;
      const d = Math.hypot(n.x - px, n.y - py);
      if (d < nearestDist) {
        nearest = n;
        nearestDist = d;
      }
    }
    return nearest;
  }

  function handleClick(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const hit = nodeAtPoint(px, py);
    onNodeClickRef.current(hit ? hit.id : null);
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const hit = nodeAtPoint(px, py);
    hoveredIdRef.current = hit ? hit.id : null;
    canvas.style.cursor = hit ? "pointer" : "default";
  }

  return (
    <canvas
      ref={canvasRef}
      onClick={handleClick}
      onMouseMove={handleMouseMove}
      style={{ width: "100%", height: "100%", display: "block" }}
    />
  );
}
