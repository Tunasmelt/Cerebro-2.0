// Stable color per cluster_id — same cluster always renders the same
// hue across re-renders/reclusters within a session, without needing a
// server-assigned color. A document with no cluster yet (uploaded since
// the last recluster) gets a fixed neutral gray, not a hashed color, so
// it visually reads as "unclustered" rather than an arbitrary cluster.

const PALETTE = [
  "#8b5cf6", // violet (brand accent)
  "#2dd4bf", // teal
  "#f59e0b", // amber
  "#ec4899", // pink
  "#3b82f6", // blue
  "#84cc16", // lime
  "#f43f5e", // rose
  "#06b6d4", // cyan
];

const UNCLUSTERED_COLOR = "#52525b"; // zinc-600 — neutral, not a cluster hue

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function clusterColor(clusterId: string | null): string {
  if (!clusterId) return UNCLUSTERED_COLOR;
  return PALETTE[hashString(clusterId) % PALETTE.length];
}
