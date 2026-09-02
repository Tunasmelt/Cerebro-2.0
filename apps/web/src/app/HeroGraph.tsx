"use client";

import { useEffect, useRef } from "react";
import type * as THREE from "three";

// Landing-page hero visual — a slowly-rotating ambient node graph in
// three.js, replacing the static hand-drawn SVG dots that used to sit
// here. Deliberately decorative and explicitly not real retrieval data
// (no auth, no vault to draw from on a marketing page) — same posture
// the real /graph page's own docs insist on ("nodes pulse only when
// actually retrieved, never simulated for effect"): this component
// never claims to be live data, it's ambient brand texture only, shown
// on a page that has no data to be honest or dishonest about.
export default function HeroGraph() {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let raf = 0;
    let disposed = false;
    let innerCleanup: (() => void) | undefined;

    (async () => {
      const THREE = await import("three");
      if (disposed || !container) return;

      const width = container.clientWidth;
      const height = container.clientHeight;

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100);
      camera.position.set(0, 0, 13);

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height);
      container.appendChild(renderer.domElement);

      const NODE_COUNT = 42;
      const positions: THREE.Vector3[] = [];
      for (let i = 0; i < NODE_COUNT; i++) {
        positions.push(
          new THREE.Vector3(
            (Math.random() - 0.5) * 11,
            (Math.random() - 0.5) * 8,
            (Math.random() - 0.5) * 6
          )
        );
      }

      // Points (nodes) — violet core nodes, a handful brighter teal
      // "retrieved-looking" accents, mirroring the real graph's palette.
      const pointGeometry = new THREE.BufferGeometry().setFromPoints(positions);
      const pointMaterial = new THREE.PointsMaterial({
        color: 0x8b5cf6,
        size: 0.14,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.9,
      });
      const points = new THREE.Points(pointGeometry, pointMaterial);

      const accentIdx = new Set<number>();
      while (accentIdx.size < 6) accentIdx.add(Math.floor(Math.random() * NODE_COUNT));
      const accentPositions = [...accentIdx].map((i) => positions[i]);
      const accentGeometry = new THREE.BufferGeometry().setFromPoints(accentPositions);
      const accentMaterial = new THREE.PointsMaterial({
        color: 0x2dd4bf,
        size: 0.22,
        sizeAttenuation: true,
        transparent: true,
        opacity: 0.95,
      });
      const accentPoints = new THREE.Points(accentGeometry, accentMaterial);

      // Edges — connect each node to its two nearest neighbors, same
      // "sparse, real-looking graph" shape the real brain graph has,
      // never a fully-connected mesh (that would look like noise, not
      // a knowledge graph).
      const lineVertices: number[] = [];
      for (let i = 0; i < NODE_COUNT; i++) {
        const distances = positions
          .map((p, j) => ({ j, d: i === j ? Infinity : p.distanceTo(positions[i]) }))
          .sort((a, b) => a.d - b.d);
        for (const { j, d } of distances.slice(0, 2)) {
          if (d < 4.5) {
            lineVertices.push(positions[i].x, positions[i].y, positions[i].z);
            lineVertices.push(positions[j].x, positions[j].y, positions[j].z);
          }
        }
      }
      const lineGeometry = new THREE.BufferGeometry();
      lineGeometry.setAttribute("position", new THREE.Float32BufferAttribute(lineVertices, 3));
      const lineMaterial = new THREE.LineBasicMaterial({
        color: 0x8b5cf6,
        transparent: true,
        opacity: 0.18,
      });
      const lines = new THREE.LineSegments(lineGeometry, lineMaterial);

      const group = new THREE.Group();
      group.add(points, lines, accentPoints);
      scene.add(group);

      let mouseX = 0;
      let mouseY = 0;
      function handlePointerMove(e: PointerEvent) {
        const rect = container!.getBoundingClientRect();
        mouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
        mouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
      }
      container.addEventListener("pointermove", handlePointerMove);

      const prefersReducedMotion = window.matchMedia?.(
        "(prefers-reduced-motion: reduce)"
      ).matches;

      function animate() {
        if (disposed) return;
        if (!prefersReducedMotion) {
          group.rotation.y += 0.0011;
          group.rotation.x += (mouseY * 0.15 - group.rotation.x) * 0.02;
          group.rotation.y += (mouseX * 0.1) * 0.001;
        }
        renderer.render(scene, camera);
        raf = requestAnimationFrame(animate);
      }
      animate();

      function handleResize() {
        if (!container) return;
        const w = container.clientWidth;
        const h = container.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      }
      window.addEventListener("resize", handleResize);

      innerCleanup = () => {
        window.removeEventListener("resize", handleResize);
        container?.removeEventListener("pointermove", handlePointerMove);
        cancelAnimationFrame(raf);
        pointGeometry.dispose();
        pointMaterial.dispose();
        accentGeometry.dispose();
        accentMaterial.dispose();
        lineGeometry.dispose();
        lineMaterial.dispose();
        renderer.dispose();
        if (container?.contains(renderer.domElement)) {
          container.removeChild(renderer.domElement);
        }
      };
      // The effect may already have been cleaned up before this async
      // setup finished (fast unmount) — run the cleanup immediately
      // instead of leaking the renderer/listeners in that case.
      if (disposed) innerCleanup();
    })();

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      innerCleanup?.();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", minHeight: 360 }}
      aria-hidden="true"
    />
  );
}
