"use client";

import { useEffect, useRef } from "react";
import type * as THREE_NS from "three";

import { clusterColor } from "@/lib/graph/clusterColor";
import type { AssociativeEdge, ChunkSatellite, GraphEdge, GraphNode } from "@/lib/graph/types";

// 3D brain graph rendering upgrade. Was a flat Canvas2D scene driven by
// d3-force; this is a real three.js WebGL scene, same dynamic-import +
// disposal pattern apps/web/src/app/HeroGraph.tsx already established
// for this repo's other three.js usage (async import("three"), a
// `disposed` flag guarding late async setup, explicit
// geometry/material/renderer/controls disposal on cleanup) — reused
// here rather than invented fresh.
//
// No new physics dependency: d3-force has no z-axis, and d3-force-3d
// (an unofficial, less-maintained fork) would break this project's
// established "hand-roll rather than add a dependency" posture (Stage
// 2.1 avoided scikit-learn, Stage 2.3 avoided a full graph-viz
// framework for the same reason). `tick3D` below is the direct 3D
// generalization of what the old d3-force setup already did in 2D:
// pairwise repulsion, per-edge spring toward a target link distance, a
// gentle centering pull to the origin, velocity damping.
//
// Node/edge similarity itself is unchanged — document_edges already
// come from real euclidean distance on full 1024-dim document centroid
// vectors (services/api/app/graph/cluster.py's compute_knn_edges,
// Stage 2.2), not the lossy projection. This file only changes how
// that data is laid out and drawn.

const NODE_RADIUS = 0.14;
const SATELLITE_RADIUS = 0.07;
const SATELLITE_ORBIT = 0.55;
// Server centroid coordinates are small floats (PCA output, typically
// well under ±5) — scaled up so nodes actually spread through the
// scene instead of clustering near the origin.
const POSITION_SCALE = 1.3;
// Brightening then fading over roughly 2 seconds is the single most
// important animation in the product (see the retrieval-pulse animation
// in Mockups/ui_kits/brain/index.html), so this duration is a
// deliberate design value, not a placeholder. Unchanged from the 2D
// version.
const PULSE_DURATION_MS = 2000;

// Hand-rolled 3D force sim constants — the direct generalization of the
// old d3-force setup (forceManyBody().strength(-80), forceLink...
// .distance(50), forceCenter, forceCollide(NODE_RADIUS * 2)), retuned
// for this file's smaller world-unit scale (POSITION_SCALE=1.3 vs the
// old 60).
//
// Repulsion is O(n^2) and its per-node total grows with n, but
// CENTERING_STRENGTH doesn't scale with n — so at a few hundred nodes,
// unbounded repulsion wins and the whole graph drifts outward forever
// (confirmed live: a real Playwright run against the 300-node perf
// harness found doc-0 projected far outside the viewport after a few
// seconds). REPULSION_CUTOFF stops a node from repelling ones already
// far away (same practical effect as d3-force's own default theta-based
// approximation, just simpler), and MAX_RADIUS is a hard safety clamp —
// regardless of how the forces balance, no node can end up further than
// this from the origin, which is what actually guarantees every node
// stays inside the camera frustum.
const REPULSION_STRENGTH = 0.35;
const REPULSION_CUTOFF = 3.5;
const LINK_DISTANCE = 1.1;
const LINK_STRENGTH = 0.05;
const CENTERING_STRENGTH = 0.045;
const DAMPING = 0.82;
const MAX_SPEED = 0.4;
const ALPHA_DECAY = 0.03; // same decay-to-alphaMin shape d3-force's
// default uses, reaching near-zero after ~230 ticks — a few seconds at
// a real 60fps browser tab; slower headless/software-rendered
// environments take longer in wall-clock time since this is tick-based,
// not time-based, matching d3-force's own convention.
const ALPHA_MIN = 0.001;
const MAX_RADIUS = 3.2; // stays comfortably inside the camera frustum
// at the default camera distance (6.5) and FOV (55°) — see the tuning
// comment above.
const COLLIDE_DISTANCE = NODE_RADIUS * 2.4;

type SimNode = {
  id: string;
  cluster_id: string | null;
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
};

/** `key` must change (e.g. incrementing counter) to re-trigger the
 * animation even when `nodeIds` is identical to the previous pulse —
 * e.g. replaying the same past conversation twice in a row. */
export type GraphPulse = { nodeIds: string[]; key: number };

export type GraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Stage 5.4 — chunk_edges (Stage 5.3) aggregated to document pairs;
   * a second, visually distinct edge layer from the kNN `edges` above.
   * Purely visual — doesn't participate in the force sim's link
   * spring, so it can't destabilize the already-tuned kNN layout. */
  associativeEdges?: AssociativeEdge[];
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
  /** Test hook: called every second with each node's current on-screen
   * pixel position (projected from its real 3D world position through
   * the camera), so a real click-interaction test can target a
   * specific node without guessing where physics settled it — same
   * pixel-space contract the old 2D version had. */
  onPositionsSample?: (positions: Record<string, { x: number; y: number }>) => void;
};

function hexToThreeColor(THREE: typeof THREE_NS, hex: string): THREE_NS.Color {
  return new THREE.Color(hex);
}

export default function GraphCanvas({
  nodes,
  edges,
  associativeEdges,
  selectedNodeId,
  satellites,
  onNodeClick,
  pulse,
  onFpsSample,
  onPositionsSample,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const simNodesRef = useRef<SimNode[]>([]);
  const nodeIdsRef = useRef<string[]>([]);
  const hoveredIdRef = useRef<string | null>(null);
  const selectedIdRef = useRef<string | null>(selectedNodeId);
  const satellitesRef = useRef<ChunkSatellite[]>(satellites);
  const edgesRef = useRef<GraphEdge[]>(edges);
  const associativeEdgesRef = useRef<AssociativeEdge[]>(associativeEdges ?? []);
  const onNodeClickRef = useRef(onNodeClick);
  const onFpsSampleRef = useRef(onFpsSample);
  const onPositionsSampleRef = useRef(onPositionsSample);
  const pulseRef = useRef<GraphPulse | null | undefined>(pulse);
  const pulseStartRef = useRef<number>(0);
  const lastPulseKeyRef = useRef<number | null>(null);
  const pointerNdcRef = useRef({ x: -10, y: -10 }); // off-canvas until first move
  // d3-force's actual settling mechanism (an "alpha" that decays each
  // tick, damping every force toward zero) — the old code inherited it
  // for free from the library; this hand-rolled version needs its own,
  // or the sim jitters forever instead of converging (confirmed live:
  // without it, a real Playwright run clicking a node's last-sampled
  // position sometimes hit a different node — the layout had visibly
  // drifted in the ~1s between sampling and clicking).
  const alphaRef = useRef(1);

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
    satellitesRef.current = satellites;
  }, [satellites]);
  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);
  useEffect(() => {
    associativeEdgesRef.current = associativeEdges ?? [];
  }, [associativeEdges]);
  useEffect(() => {
    pulseRef.current = pulse;
    if (pulse && pulse.key !== lastPulseKeyRef.current) {
      pulseStartRef.current = performance.now();
      lastPulseKeyRef.current = pulse.key;
    }
  }, [pulse]);

  // Rebuild the sim node set whenever the node set itself changes — not
  // on every selection/satellite/edge change, which would otherwise
  // restart physics and jitter the whole graph from a click.
  useEffect(() => {
    simNodesRef.current = nodes.map((n) => ({
      id: n.id,
      cluster_id: n.cluster_id,
      x: n.x != null ? n.x * POSITION_SCALE : (Math.random() - 0.5) * 2,
      y: n.y != null ? n.y * POSITION_SCALE : (Math.random() - 0.5) * 2,
      z: n.z != null ? n.z * POSITION_SCALE : (Math.random() - 0.5) * 2,
      vx: 0,
      vy: 0,
      vz: 0,
    }));
    nodeIdsRef.current = simNodesRef.current.map((n) => n.id);
    alphaRef.current = 1; // fresh layout — full energy, then cools down
  }, [nodes]);

  // Scene setup — runs once per mount, independent of data changes
  // (data is read live off the refs above inside the animation loop).
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let raf = 0;
    let disposed = false;
    let innerCleanup: (() => void) | undefined;

    (async () => {
      const THREE = await import("three");
      const { OrbitControls } = await import(
        "three/examples/jsm/controls/OrbitControls.js"
      );
      if (disposed || !container) return;

      const width = container.clientWidth;
      const height = container.clientHeight;

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(55, width / height, 0.1, 200);
      camera.position.set(0, 0, 6.5);

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(width, height);
      renderer.setClearColor(0x0a0a0f, 1);
      container.appendChild(renderer.domElement);

      // Real data the user is trying to read, not decoration — orbit
      // only moves in response to the user, never auto-rotates.
      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.minDistance = 1.5;
      controls.maxDistance = 40;

      const MAX_NODES = 4000; // generous static capacity for InstancedMesh
      const nodeGeometry = new THREE.SphereGeometry(NODE_RADIUS, 12, 12);
      const nodeMaterial = new THREE.MeshBasicMaterial({ toneMapped: false });
      const nodeMesh = new THREE.InstancedMesh(nodeGeometry, nodeMaterial, MAX_NODES);
      nodeMesh.instanceColor = new THREE.InstancedBufferAttribute(
        new Float32Array(MAX_NODES * 3),
        3
      );
      scene.add(nodeMesh);

      const satelliteGeometry = new THREE.SphereGeometry(SATELLITE_RADIUS, 8, 8);
      const satelliteMaterial = new THREE.MeshBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 0.85,
        toneMapped: false,
      });
      const MAX_SATELLITES = 64;
      const satelliteMesh = new THREE.InstancedMesh(
        satelliteGeometry,
        satelliteMaterial,
        MAX_SATELLITES
      );
      satelliteMesh.count = 0;
      scene.add(satelliteMesh);

      const edgeGeometry = new THREE.BufferGeometry();
      const edgeMaterial = new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.9,
      });
      const edgeLines = new THREE.LineSegments(edgeGeometry, edgeMaterial);
      scene.add(edgeLines);

      // Stage 5.4 — a second, visually distinct edge layer for
      // associative (chunk-derived) edges: thin and low-opacity by
      // default, brightening with weight. LineBasicMaterial can't vary
      // width per-segment (real variable-width lines need three's
      // fatline addon, not worth the extra complexity here), so
      // "thickens with weight" is expressed as opacity/brightness
      // instead — still clearly reads as "stronger connection" without
      // a second rendering pipeline.
      const associativeEdgeGeometry = new THREE.BufferGeometry();
      const associativeEdgeMaterial = new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.8,
      });
      const associativeEdgeLines = new THREE.LineSegments(
        associativeEdgeGeometry,
        associativeEdgeMaterial
      );
      scene.add(associativeEdgeLines);

      const satelliteLineGeometry = new THREE.BufferGeometry();
      const satelliteLineMaterial = new THREE.LineBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 0.15,
      });
      const satelliteLines = new THREE.LineSegments(satelliteLineGeometry, satelliteLineMaterial);
      scene.add(satelliteLines);

      const raycaster = new THREE.Raycaster();
      const dummy = new THREE.Object3D();
      const tmpColor = new THREE.Color();
      const worldVec = new THREE.Vector3();

      function tick3D() {
        const simNodes = simNodesRef.current;
        const n = simNodes.length;
        if (n === 0) return;

        const alpha = alphaRef.current;
        if (alpha <= ALPHA_MIN) return; // settled — nothing left to do

        // Pairwise repulsion — O(n^2), fine at the few-hundred-node
        // scale this graph targets (same scale Stage 2.3's own 300-doc
        // perf bar already covers).
        for (let i = 0; i < n; i++) {
          const a = simNodes[i];
          for (let j = i + 1; j < n; j++) {
            const b = simNodes[j];
            let dx = a.x - b.x;
            let dy = a.y - b.y;
            let dz = a.z - b.z;
            let distSq = dx * dx + dy * dy + dz * dz;
            if (distSq < 0.0001) {
              dx = Math.random() * 0.01;
              dy = Math.random() * 0.01;
              dz = Math.random() * 0.01;
              distSq = 0.0001;
            }
            const dist = Math.sqrt(distSq);
            if (dist > REPULSION_CUTOFF) continue;
            const force = (REPULSION_STRENGTH / distSq) * alpha;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            const fz = (dz / dist) * force;
            a.vx += fx;
            a.vy += fy;
            a.vz += fz;
            b.vx -= fx;
            b.vy -= fy;
            b.vz -= fz;
            // Collision — a hard minimum-separation push, same role
            // the old d3 forceCollide(NODE_RADIUS * 2) played.
            if (dist < COLLIDE_DISTANCE) {
              const push = (COLLIDE_DISTANCE - dist) * 0.5;
              const px = (dx / dist) * push;
              const py = (dy / dist) * push;
              const pz = (dz / dist) * push;
              a.x += px;
              a.y += py;
              a.z += pz;
              b.x -= px;
              b.y -= py;
              b.z -= pz;
            }
          }
        }

        // Link spring — pulls connected nodes toward LINK_DISTANCE.
        const idToNode = new Map(simNodes.map((sn) => [sn.id, sn]));
        for (const e of edgesRef.current) {
          const a = idToNode.get(e.document_id);
          const b = idToNode.get(e.neighbor_document_id);
          if (!a || !b) continue;
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dz = b.z - a.z;
          const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 0.0001;
          const diff = (dist - LINK_DISTANCE) * LINK_STRENGTH * alpha;
          const fx = (dx / dist) * diff;
          const fy = (dy / dist) * diff;
          const fz = (dz / dist) * diff;
          a.vx += fx;
          a.vy += fy;
          a.vz += fz;
          b.vx -= fx;
          b.vy -= fy;
          b.vz -= fz;
        }

        // Centering + integrate + damp, then two safety clamps that
        // hold regardless of how the forces above balance: a max speed
        // (stops one bad frame from flinging a node into orbit) and a
        // max radius from the origin (guarantees every node stays
        // inside the camera frustum — see this file's tuning comment
        // above for why the forces alone can't be trusted to converge).
        for (const sn of simNodes) {
          sn.vx += -sn.x * CENTERING_STRENGTH * alpha;
          sn.vy += -sn.y * CENTERING_STRENGTH * alpha;
          sn.vz += -sn.z * CENTERING_STRENGTH * alpha;
          sn.vx *= DAMPING;
          sn.vy *= DAMPING;
          sn.vz *= DAMPING;
          const speed = Math.hypot(sn.vx, sn.vy, sn.vz);
          if (speed > MAX_SPEED) {
            const s = MAX_SPEED / speed;
            sn.vx *= s;
            sn.vy *= s;
            sn.vz *= s;
          }
          sn.x += sn.vx;
          sn.y += sn.vy;
          sn.z += sn.vz;
          const radius = Math.hypot(sn.x, sn.y, sn.z);
          if (radius > MAX_RADIUS) {
            const s = MAX_RADIUS / radius;
            sn.x *= s;
            sn.y *= s;
            sn.z *= s;
          }
        }

        alphaRef.current = Math.max(ALPHA_MIN, alpha * (1 - ALPHA_DECAY));
      }

      function updateNodeInstances() {
        const simNodes = simNodesRef.current;
        const now0 = performance.now();
        const activePulse = pulseRef.current;
        const pulseElapsed = activePulse ? now0 - pulseStartRef.current : Infinity;
        const pulseActive = !!activePulse && pulseElapsed < PULSE_DURATION_MS;
        const pulseIntensity = pulseActive ? 1 - pulseElapsed / PULSE_DURATION_MS : 0;
        const pulsingIds = pulseActive ? new Set(activePulse!.nodeIds) : null;

        nodeMesh.count = simNodes.length;
        for (let i = 0; i < simNodes.length; i++) {
          const sn = simNodes[i];
          const isFocus = sn.id === selectedIdRef.current || sn.id === hoveredIdRef.current;
          const isPulsing = pulsingIds?.has(sn.id) ?? false;
          const scale = isPulsing
            ? 1.4 + 0.9 * pulseIntensity
            : isFocus
              ? 1.6
              : 1;
          dummy.position.set(sn.x, sn.y, sn.z);
          dummy.scale.setScalar(scale);
          dummy.updateMatrix();
          nodeMesh.setMatrixAt(i, dummy.matrix);

          const baseColor = clusterColor(sn.cluster_id);
          tmpColor.set(baseColor);
          if (isPulsing) {
            tmpColor.lerp(new THREE.Color(0xffffff), 0.5 + 0.5 * pulseIntensity);
          } else if (isFocus) {
            tmpColor.lerp(new THREE.Color(0xffffff), 0.35);
          }
          nodeMesh.setColorAt(i, tmpColor);
        }
        nodeMesh.instanceMatrix.needsUpdate = true;
        if (nodeMesh.instanceColor) nodeMesh.instanceColor.needsUpdate = true;
      }

      // Rebuilding the edge geometry allocates two fresh arrays and
      // walks every edge — cheap once, wasteful every single frame once
      // the layout has settled and focus hasn't changed (confirmed live:
      // this was the single biggest steady-state cost in headless
      // testing, where WebGL is software-rendered and every allocation
      // shows up directly in the FPS readout). Skipped once alpha has
      // bottomed out and neither hover nor selection moved since the
      // last frame — resumed instantly the moment either does.
      let lastEdgeFocusKey = "";
      function updateEdges() {
        const focusKey = `${selectedIdRef.current}|${hoveredIdRef.current}`;
        const settled = alphaRef.current <= ALPHA_MIN;
        if (settled && focusKey === lastEdgeFocusKey) return;
        lastEdgeFocusKey = focusKey;

        const simNodes = simNodesRef.current;
        const idToNode = new Map(simNodes.map((sn) => [sn.id, sn]));
        const positions: number[] = [];
        const colors: number[] = [];
        for (const e of edgesRef.current) {
          const a = idToNode.get(e.document_id);
          const b = idToNode.get(e.neighbor_document_id);
          if (!a || !b) continue;
          const touchesFocus =
            e.document_id === selectedIdRef.current ||
            e.neighbor_document_id === selectedIdRef.current ||
            e.document_id === hoveredIdRef.current ||
            e.neighbor_document_id === hoveredIdRef.current;
          positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
          const c = touchesFocus
            ? hexToThreeColor(THREE, "#8b5cf6")
            : hexToThreeColor(THREE, "#3f3f4a");
          colors.push(c.r, c.g, c.b, c.r, c.g, c.b);
        }
        edgeGeometry.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(positions, 3)
        );
        edgeGeometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
        edgeGeometry.computeBoundingSphere();
      }

      // Same steady-state skip as updateEdges, plus this layer only
      // needs rebuilding when the associative edge set itself changes
      // (it doesn't participate in hover/selection highlighting the way
      // kNN edges do, so focus changes don't need to invalidate it).
      let lastAssociativeEdgesRebuiltFor: AssociativeEdge[] | null = null;
      function updateAssociativeEdges() {
        const currentEdges = associativeEdgesRef.current;
        const settled = alphaRef.current <= ALPHA_MIN;
        if (settled && currentEdges === lastAssociativeEdgesRebuiltFor) return;
        lastAssociativeEdgesRebuiltFor = currentEdges;

        const simNodes = simNodesRef.current;
        const idToNode = new Map(simNodes.map((sn) => [sn.id, sn]));
        const positions: number[] = [];
        const colors: number[] = [];
        const maxWeight = Math.max(1, ...currentEdges.map((e) => e.weight));
        const baseColor = hexToThreeColor(THREE, "#2dd4bf"); // teal —
        // distinct from the violet kNN edges above.
        for (const e of currentEdges) {
          const a = idToNode.get(e.document_id);
          const b = idToNode.get(e.neighbor_document_id);
          if (!a || !b) continue;
          positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
          // "Thickens with weight" per this stage's exit criteria,
          // expressed as brightness/opacity since per-segment line
          // width isn't available with LineBasicMaterial — an explicit
          // link (already weighted well above any co-retrieval sum)
          // reads as fully bright regardless of the current max.
          const intensity = e.is_explicit ? 1 : Math.min(1, e.weight / maxWeight);
          const c = tmpColor.copy(baseColor).multiplyScalar(0.25 + 0.75 * intensity);
          colors.push(c.r, c.g, c.b, c.r, c.g, c.b);
        }
        associativeEdgeGeometry.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(positions, 3)
        );
        associativeEdgeGeometry.setAttribute(
          "color",
          new THREE.Float32BufferAttribute(colors, 3)
        );
        associativeEdgeGeometry.computeBoundingSphere();
      }

      function updateSatellites() {
        const simNodes = simNodesRef.current;
        const idToNode = new Map(simNodes.map((sn) => [sn.id, sn]));
        const parent = selectedIdRef.current ? idToNode.get(selectedIdRef.current) : null;
        const sats = satellitesRef.current;

        if (!parent || sats.length === 0) {
          satelliteMesh.count = 0;
          satelliteLineGeometry.setAttribute(
            "position",
            new THREE.Float32BufferAttribute([], 3)
          );
          return;
        }

        // Golden-angle spiral distributes satellites evenly over a
        // sphere around the parent, instead of the old flat 2D circle.
        const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
        const count = Math.min(sats.length, MAX_SATELLITES);
        satelliteMesh.count = count;
        const linePositions: number[] = [];
        for (let i = 0; i < count; i++) {
          const t = count > 1 ? i / (count - 1) : 0;
          const inclination = Math.acos(1 - 2 * t);
          const azimuth = GOLDEN_ANGLE * i;
          const sx = parent.x + SATELLITE_ORBIT * Math.sin(inclination) * Math.cos(azimuth);
          const sy = parent.y + SATELLITE_ORBIT * Math.sin(inclination) * Math.sin(azimuth);
          const sz = parent.z + SATELLITE_ORBIT * Math.cos(inclination);
          dummy.position.set(sx, sy, sz);
          dummy.scale.setScalar(1);
          dummy.updateMatrix();
          satelliteMesh.setMatrixAt(i, dummy.matrix);
          linePositions.push(parent.x, parent.y, parent.z, sx, sy, sz);
        }
        satelliteMesh.instanceMatrix.needsUpdate = true;
        satelliteLineGeometry.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(linePositions, 3)
        );
      }

      let frameCount = 0;
      let lastFpsTime = performance.now();

      // Shared by the per-frame hover raycast and the click handler.
      // Click deliberately does NOT reuse hoveredIdRef — that's only
      // ever as fresh as the last animation frame, and a real
      // mousemove-then-click pair (e.g. Playwright's Mouse.click, which
      // dispatches a real move before the click) can land inside the
      // same JS turn, before rAF has run again. Raycasting fresh here
      // removes that race instead of hoping the frame timing lines up.
      function pickNodeIdAt(ndcX: number, ndcY: number): string | null {
        raycaster.setFromCamera({ x: ndcX, y: ndcY } as THREE_NS.Vector2, camera);
        const hits = raycaster.intersectObject(nodeMesh);
        return hits.length > 0 && hits[0].instanceId != null
          ? nodeIdsRef.current[hits[0].instanceId]
          : null;
      }

      function draw() {
        tick3D();
        updateNodeInstances();
        updateEdges();
        updateAssociativeEdges();
        updateSatellites();

        // Hover picking against the real current instance positions.
        const hitId = pickNodeIdAt(pointerNdcRef.current.x, pointerNdcRef.current.y);
        hoveredIdRef.current = hitId;
        renderer.domElement.style.cursor = hitId ? "pointer" : "default";

        controls.update();
        renderer.render(scene, camera);

        const now0 = performance.now();
        frameCount++;
        if (now0 - lastFpsTime >= 1000) {
          onFpsSampleRef.current?.(frameCount / ((now0 - lastFpsTime) / 1000));
          frameCount = 0;
          lastFpsTime = now0;
          if (onPositionsSampleRef.current) {
            const rect = renderer.domElement.getBoundingClientRect();
            const positions: Record<string, { x: number; y: number }> = {};
            for (const sn of simNodesRef.current) {
              worldVec.set(sn.x, sn.y, sn.z).project(camera);
              positions[sn.id] = {
                x: ((worldVec.x + 1) / 2) * rect.width,
                y: ((1 - worldVec.y) / 2) * rect.height,
              };
            }
            onPositionsSampleRef.current(positions);
          }
        }

        raf = requestAnimationFrame(draw);
      }
      raf = requestAnimationFrame(draw);

      function pointerToNdc(e: PointerEvent) {
        const rect = renderer.domElement.getBoundingClientRect();
        pointerNdcRef.current = {
          x: ((e.clientX - rect.left) / rect.width) * 2 - 1,
          y: -((e.clientY - rect.top) / rect.height) * 2 + 1,
        };
      }
      function handlePointerMove(e: PointerEvent) {
        pointerToNdc(e);
      }
      function handleClick(e: PointerEvent) {
        pointerToNdc(e);
        onNodeClickRef.current(pickNodeIdAt(pointerNdcRef.current.x, pointerNdcRef.current.y));
      }
      renderer.domElement.addEventListener("pointermove", handlePointerMove);
      renderer.domElement.addEventListener("click", handleClick);

      function handleResize() {
        if (!container) return;
        const w = container.clientWidth;
        const h = container.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      }
      window.addEventListener("resize", handleResize);
      // AppShell wraps this page in a flex layout — the container can
      // change size from sidebar collapse/expand or content reflow
      // without the window itself ever firing a resize event, which
      // would leave the camera aspect ratio and click raycasting math
      // stale (computed against whatever size existed at mount) until
      // the next real window resize. ResizeObserver catches that case
      // too; the standalone perf-test harness (100vw/100vh, no flex
      // ancestor) never exercised this gap.
      const resizeObserver = new ResizeObserver(handleResize);
      resizeObserver.observe(container);

      innerCleanup = () => {
        window.removeEventListener("resize", handleResize);
        resizeObserver.disconnect();
        renderer.domElement.removeEventListener("pointermove", handlePointerMove);
        renderer.domElement.removeEventListener("click", handleClick);
        cancelAnimationFrame(raf);
        controls.dispose();
        nodeGeometry.dispose();
        nodeMaterial.dispose();
        satelliteGeometry.dispose();
        satelliteMaterial.dispose();
        edgeGeometry.dispose();
        edgeMaterial.dispose();
        associativeEdgeGeometry.dispose();
        associativeEdgeMaterial.dispose();
        satelliteLineGeometry.dispose();
        satelliteLineMaterial.dispose();
        renderer.dispose();
        if (container?.contains(renderer.domElement)) {
          container.removeChild(renderer.domElement);
        }
      };
      if (disposed) innerCleanup();
    })();

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      innerCleanup?.();
    };
  }, []);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
