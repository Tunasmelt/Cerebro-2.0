import { describe, expect, it } from "vitest";

import { graphMatches, graphNodeIsDimmed } from "./search";
import type { GraphNode } from "./types";

const nodes: GraphNode[] = [
  { id: "1", title: "Raft Notes", cluster_id: null, x: 0, y: 0, z: 0 },
  { id: "2", title: "Paxos Paper", cluster_id: null, x: 1, y: 1, z: 1 },
];

describe("graph search presentation", () => {
  it("matches case-insensitively without reshaping the source array", () => {
    expect(graphMatches(nodes, "RAFT").map((node) => node.id)).toEqual(["1"]);
    expect(nodes).toHaveLength(2);
  });

  it("dims nonmatches but never dims the selected node", () => {
    expect(graphNodeIsDimmed(nodes[1], "raft", null)).toBe(true);
    expect(graphNodeIsDimmed(nodes[1], "raft", "2")).toBe(false);
  });
});
