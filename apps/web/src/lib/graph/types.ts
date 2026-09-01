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
