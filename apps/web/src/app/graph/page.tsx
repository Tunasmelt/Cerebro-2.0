"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import AppShell from "@/components/AppShell";
import { authedFetch } from "@/lib/api";
import { parseAnswerSegments, stripCitationMarkers } from "@/lib/graph/citations";
import { clusterColor } from "@/lib/graph/clusterColor";
import { parseSSEStream } from "@/lib/graph/sse";
import type {
  ChatMessage,
  ChatSession,
  ChunkSatellite,
  GraphEdge,
  GraphNode,
} from "@/lib/graph/types";
import { useAuthedUser } from "@/lib/useAuthedUser";
import GraphCanvas, { type GraphPulse } from "./GraphCanvas";
import styles from "./graph.module.css";

// Stage 2.4: replaying a past conversation plays each of its retrieval
// pulses in order, one at a time — this is the pause between them.
const REPLAY_PULSE_INTERVAL_MS = 2400;

// UI gap #2 (Phase 0-2 audit): nodes/edges were only ever fetched once
// on mount, so a document uploaded elsewhere needed a full reload to
// show up — contra the Phase 2 Gate's own "watched the graph update
// without a full reload" wording. Polling both together stays well
// under the "graph" rate-limit class (60/min per user; this is 24/min).
const GRAPH_POLL_INTERVAL_MS = 5000;

type Citation = { chunk_id: string; document_id: string };

export default function GraphPage() {
  const router = useRouter();
  const { checking, email } = useAuthedUser();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [satellites, setSatellites] = useState<ChunkSatellite[]>([]);
  const [legendOpen, setLegendOpen] = useState(true);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [pulse, setPulse] = useState<GraphPulse | null>(null);
  const pulseKeyRef = useRef(0);

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [replaying, setReplaying] = useState(false);

  // Refs, not state, for the last-seen payloads — comparing here avoids
  // handing GraphCanvas a new array reference (which restarts its
  // d3-force simulation, see GraphCanvas.tsx) on every poll tick when
  // nothing actually changed.
  const lastNodesJsonRef = useRef<string>("");
  const lastEdgesJsonRef = useRef<string>("");

  const fetchGraph = useCallback(async () => {
    const [nodesRes, edgesRes] = await Promise.all([
      authedFetch("/api/graph/nodes"),
      authedFetch("/api/graph/edges"),
    ]);
    const nodesBody = await nodesRes.json();
    const edgesBody = await edgesRes.json();
    const nodesJson = JSON.stringify(nodesBody.nodes ?? []);
    const edgesJson = JSON.stringify(edgesBody.edges ?? []);
    if (nodesJson !== lastNodesJsonRef.current) {
      lastNodesJsonRef.current = nodesJson;
      setNodes(nodesBody.nodes ?? []);
    }
    if (edgesJson !== lastEdgesJsonRef.current) {
      lastEdgesJsonRef.current = edgesJson;
      setEdges(edgesBody.edges ?? []);
    }
  }, []);

  useEffect(() => {
    if (checking) return;
    fetchGraph();
    const interval = setInterval(fetchGraph, GRAPH_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [checking, fetchGraph]);

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

  function triggerPulse(documentIds: string[]) {
    pulseKeyRef.current += 1;
    setPulse({ nodeIds: documentIds, key: pulseKeyRef.current });
  }

  async function ensureSession(): Promise<string> {
    if (sessionId) return sessionId;
    const res = await authedFetch("/api/chat/sessions", { method: "POST" });
    const body = await res.json();
    setSessionId(body.id);
    return body.id;
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || streaming) return;

    setChatError(null);
    setAnswer("");
    setCitations([]);
    setStreaming(true);
    setQuery("");

    try {
      const activeSessionId = await ensureSession();
      const res = await authedFetch(
        `/api/chat/sessions/${activeSessionId}/stream`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ query: trimmed }),
        }
      );
      if (!res.body) throw new Error("no response body");

      for await (const evt of parseSSEStream(res.body)) {
        if (evt.event === "retrieval") {
          const data = evt.data as { chunk_ids: string[]; document_ids: string[] };
          // The real retrieval event's document_ids, verbatim — this is
          // the exit criteria's "pulses exactly the returned document
          // nodes", not a derived or re-computed set.
          triggerPulse(data.document_ids);
        } else if (evt.event === "token") {
          const data = evt.data as { text: string };
          setAnswer((prev) => prev + data.text);
        } else if (evt.event === "citation") {
          const data = evt.data as Citation;
          setCitations((prev) => [...prev, data]);
        } else if (evt.event === "error") {
          const data = evt.data as { message: string };
          setChatError(data.message || "Something went wrong");
        }
      }
    } catch {
      setChatError("Connection failed");
    } finally {
      setStreaming(false);
    }
  }

  async function openSessionList() {
    setSessionsOpen((open) => !open);
    if (sessions.length === 0) {
      const res = await authedFetch("/api/chat/sessions");
      const body = await res.json();
      setSessions(body.sessions ?? []);
    }
  }

  async function replaySession(id: string) {
    setSessionsOpen(false);
    setReplaying(true);
    try {
      const res = await authedFetch(`/api/chat/sessions/${id}/messages`);
      const body = await res.json();
      const messages: ChatMessage[] = body.messages ?? [];
      const pulses = messages.filter((m) => m.retrieved_document_ids.length > 0);
      for (const m of pulses) {
        triggerPulse(m.retrieved_document_ids);
        await new Promise((resolve) => setTimeout(resolve, REPLAY_PULSE_INTERVAL_MS));
      }
    } finally {
      setReplaying(false);
    }
  }

  if (checking) return null;

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;

  // While streaming, citation events (the only source of truth for
  // which markers are real) haven't all arrived yet — show clean prose
  // rather than raw [[chunk:...]] syntax. Once done, resolve each
  // marker against the real citations collected during the stream;
  // clicking one selects that node on the graph, same as clicking it
  // directly.
  function renderAnswer() {
    if (streaming) return stripCitationMarkers(answer) || "…";
    return parseAnswerSegments(answer).map((seg, i) => {
      if (seg.type === "text") return <span key={i}>{seg.text}</span>;
      const index = citations.findIndex((c) => c.chunk_id === seg.chunkId);
      if (index === -1) return null; // dropped marker, not a real citation
      const citation = citations[index];
      return (
        <button
          key={i}
          type="button"
          className={styles.citeChip}
          onClick={() => handleNodeClick(citation.document_id)}
          title={`Jump to source ${index + 1}`}
        >
          {index + 1}
        </button>
      );
    });
  }

  return (
    <AppShell userEmail={email}>
    <div className={styles.page}>
      <div className={styles.canvasWrap}>
        <GraphCanvas
          nodes={nodes}
          edges={edges}
          selectedNodeId={selectedNodeId}
          satellites={satellites}
          onNodeClick={handleNodeClick}
          pulse={pulse}
        />
      </div>

      <span className={styles.docsLink} onClick={() => router.push("/documents")}>
        Documents
      </span>

      {nodes.length === 0 && (
        <div className={styles.emptyState}>
          <p style={{ margin: 0 }}>Your graph will start forming as soon as it lands.</p>
          <button className={styles.emptyStateCta} onClick={() => router.push("/documents")}>
            Upload your first document
          </button>
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

      <div className={styles.chatDock}>
        {chatError && <div className={styles.chatError}>{chatError}</div>}
        {(streaming || answer) && (
          <div className={styles.chatAnswer}>{renderAnswer()}</div>
        )}
        <form className={styles.chatForm} onSubmit={handleSend}>
          <button
            type="button"
            className={styles.sessionsButton}
            onClick={openSessionList}
            aria-label="Past conversations"
            disabled={replaying}
          >
            {replaying ? "replaying…" : "history"}
          </button>
          <input
            className={styles.chatInput}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask about your documents…"
            disabled={streaming}
          />
          <button type="submit" className={styles.chatSend} disabled={streaming}>
            {streaming ? "…" : "Ask"}
          </button>
        </form>

        {sessionsOpen && (
          <div className={styles.sessionsPanel}>
            {sessions.length === 0 && (
              <p className={styles.chunkItem}>No past conversations yet.</p>
            )}
            {sessions.map((s) => (
              <button
                key={s.id}
                className={styles.sessionItem}
                onClick={() => replaySession(s.id)}
              >
                {new Date(s.created_at).toLocaleString()}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
    </AppShell>
  );
}
