import type { GraphNode } from "./types";

export function graphMatches(nodes: GraphNode[], query: string): GraphNode[] {
  const normalized = query.trim().toLowerCase();
  return normalized ? nodes.filter((node) => node.title.toLowerCase().includes(normalized)) : [];
}

export function graphNodeIsDimmed(node: Pick<GraphNode, "id" | "title">, query: string, selectedNodeId: string | null): boolean {
  const normalized = query.trim().toLowerCase();
  return normalized.length > 0 && node.id !== selectedNodeId && !node.title.toLowerCase().includes(normalized);
}
