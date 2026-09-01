export type GraphNode = {
  id: string;
  title: string;
  cluster_id: string | null;
  x: number | null;
  y: number | null;
};

export type GraphEdge = {
  document_id: string;
  neighbor_document_id: string;
  distance: number;
  rank: number;
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
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  retrieved_chunk_ids: string[];
  retrieved_document_ids: string[];
  created_at: string;
};

export type DocumentStatus = "processing" | "ready" | "failed" | "sealed";

export type DocumentRow = {
  id: string;
  title: string;
  mime: string;
  size_bytes: number;
  status: DocumentStatus;
  created_at: string;
};
