// Node type/sealed coloring pass — mime/status were already columns on
// `documents`, get_nodes (services/api/app/graph/storage.py) now
// includes them per node so the graph can color by type and distinguish
// a sealed node without a second per-node request. Also fixed a real
// bug: get_nodes used to filter status=eq.ready only, so sealing a
// document made its node vanish from the graph entirely.
export type GraphNode = {
  id: string;
  title: string;
  cluster_id: string | null;
  x: number | null;
  y: number | null;
  z: number | null;
  mime?: string | null;
  status?: "ready" | "sealed";
};

export type GraphEdge = {
  document_id: string;
  neighbor_document_id: string;
  distance: number;
  rank: number;
};

// Stage 5.4 — chunk_edges (Stage 5.3) aggregated up to document pairs,
// a second, visually distinct layer alongside GraphEdge's kNN edges.
export type AssociativeEdge = {
  document_id: string;
  neighbor_document_id: string;
  weight: number;
  is_explicit: boolean;
};

export type ChunkSatellite = {
  id: string;
  ordinal: number;
  content: string;
  meta: Record<string, unknown>;
};

export type ChatSession = {
  id: string;
  created_at: string;
  // Chat management pass — earliest user message, truncated, or null
  // for a session with no user message yet.
  preview?: string | null;
};

// Chat management pass — real per-message citation resolution
// (chunk_id/document_id/document_title, first-appearance order),
// reusing the exact same extract_citations a live turn uses. Fixes a
// real gap: reopening a past conversation used to only ever pulse the
// graph, never render the answer text with working citation chips.
export type Citation = {
  chunk_id: string;
  document_id: string;
  document_title: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  retrieved_chunk_ids: string[];
  retrieved_document_ids: string[];
  citations?: Citation[];
  created_at: string;
};

export type DocumentStatus = "processing" | "ready" | "failed" | "sealed";

export type DocumentRow = {
  id: string;
  title: string;
  mime: string;
  size_bytes: number;
  original_size_bytes: number | null;
  status: DocumentStatus;
  created_at: string;
};
