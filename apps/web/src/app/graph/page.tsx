"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import AnswerMarkdown from "@/components/AnswerMarkdown";
import AppShell from "@/components/AppShell";
import { authedFetch } from "@/lib/api";
import { parseSSEStream } from "@/lib/graph/sse";
import type {
  AssociativeEdge,
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

function GraphPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { checking, email } = useAuthedUser();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [associativeEdges, setAssociativeEdges] = useState<AssociativeEdge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [satellites, setSatellites] = useState<ChunkSatellite[]>([]);
  const [legendOpen, setLegendOpen] = useState(true);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [streaming, setStreaming] = useState(false);
  // Stage 7.11 — bumped on each `heartbeat` SSE event (services/api's
  // chat/stream.py, fired while retrieval/HyDE is still running and no
  // token has arrived yet), so a slow turn visibly shows it's still
  // working instead of looking frozen. Purely a render trigger/counter
  // — the actual "still thinking" copy is derived from it in
  // renderAnswer() below.
  const [heartbeatCount, setHeartbeatCount] = useState(0);
  const [chatError, setChatError] = useState<string | null>(null);
  const [pulse, setPulse] = useState<GraphPulse | null>(null);
  const pulseKeyRef = useRef(0);

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [replaying, setReplaying] = useState(false);
  // Distinguishes "still loading the first poll" from "genuinely no
  // documents yet" — without this the empty-state CTA flashed on every
  // load, even for accounts with plenty of documents, until the first
  // fetch resolved.
  const [loadingGraph, setLoadingGraph] = useState(true);
  const sessionsPanelRef = useRef<HTMLDivElement | null>(null);
  const sessionsButtonRef = useRef<HTMLButtonElement | null>(null);
  const chatInputRef = useRef<HTMLInputElement | null>(null);

  // Refs, not state, for the last-seen payloads — comparing here avoids
  // handing GraphCanvas a new array reference (which restarts its
  // d3-force simulation, see GraphCanvas.tsx) on every poll tick when
  // nothing actually changed.
  const lastNodesJsonRef = useRef<string>("");
  const lastEdgesJsonRef = useRef<string>("");
  const lastAssociativeEdgesJsonRef = useRef<string>("");

  const fetchGraph = useCallback(async () => {
    const [nodesRes, edgesRes] = await Promise.all([
      authedFetch("/api/graph/nodes"),
      authedFetch("/api/graph/edges?include=associative"),
    ]);
    const nodesBody = await nodesRes.json();
    const edgesBody = await edgesRes.json();
    const nodesJson = JSON.stringify(nodesBody.nodes ?? []);
    const edgesJson = JSON.stringify(edgesBody.edges ?? []);
    const associativeEdgesJson = JSON.stringify(edgesBody.associative_edges ?? []);
    if (nodesJson !== lastNodesJsonRef.current) {
      lastNodesJsonRef.current = nodesJson;
      setNodes(nodesBody.nodes ?? []);
    }
    if (edgesJson !== lastEdgesJsonRef.current) {
      lastEdgesJsonRef.current = edgesJson;
      setEdges(edgesBody.edges ?? []);
    }
    if (associativeEdgesJson !== lastAssociativeEdgesJsonRef.current) {
      lastAssociativeEdgesJsonRef.current = associativeEdgesJson;
      setAssociativeEdges(edgesBody.associative_edges ?? []);
    }
  }, []);

  useEffect(() => {
    if (checking) return;
    fetchGraph().finally(() => setLoadingGraph(false));
    const interval = setInterval(fetchGraph, GRAPH_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [checking, fetchGraph]);

  // Escape closes whichever overlay is open, most-recently-opened
  // first — sessions panel sits "on top of" the side panel visually,
  // so it should be the first thing Escape dismisses. "/" focuses the
  // chat input from anywhere on the page (skipped while already typing
  // in a field, so it doesn't hijack a literal "/" character).
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (sessionsOpen) {
          setSessionsOpen(false);
        } else if (selectedNodeId) {
          setSelectedNodeId(null);
          setSatellites([]);
        }
        return;
      }
      if (e.key === "/") {
        const target = e.target as HTMLElement;
        const isTyping =
          target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
        if (isTyping) return;
        e.preventDefault();
        chatInputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [sessionsOpen, selectedNodeId]);

  // Click-outside closes the sessions panel, same as any dropdown.
  useEffect(() => {
    if (!sessionsOpen) return;
    function handlePointerDown(e: MouseEvent) {
      const target = e.target as Node;
      if (
        !sessionsPanelRef.current?.contains(target) &&
        !sessionsButtonRef.current?.contains(target)
      ) {
        setSessionsOpen(false);
      }
    }
    window.addEventListener("mousedown", handlePointerDown);
    return () => window.removeEventListener("mousedown", handlePointerDown);
  }, [sessionsOpen]);

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
      // A sealed document's chunks were deleted from `chunks` when it
      // was sealed (Stage 3.3) — fetching would just come back empty,
      // so skip the request and let the panel show the sealed state
      // directly instead of a confusing "No chunks yet."
      const node = nodes.find((n) => n.id === nodeId);
      if (node?.status === "sealed") return;
      authedFetch(`/api/graph/nodes/${nodeId}/chunks`)
        .then((res) => res.json())
        .then((body) => setSatellites(body.chunks ?? []));
    },
    [selectedNodeId, nodes]
  );

  // A cross-page link (e.g. /chat's citation chips) lands here with
  // ?focus=<document_id> — select that node once, on mount.
  const focusHandledRef = useRef(false);
  useEffect(() => {
    if (focusHandledRef.current || nodes.length === 0) return;
    const focusId = searchParams.get("focus");
    if (!focusId) return;
    focusHandledRef.current = true;
    if (nodes.some((n) => n.id === focusId)) handleNodeClick(focusId);
  }, [searchParams, nodes, handleNodeClick]);

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

  async function sendQuery(trimmed: string) {
    if (!trimmed || streaming) return;

    setChatError(null);
    setAnswer("");
    setCitations([]);
    setStreaming(true);
    setHeartbeatCount(0);
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
        if (evt.event === "heartbeat") {
          setHeartbeatCount((prev) => prev + 1);
        } else if (evt.event === "retrieval") {
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

  function handleSend(e: React.FormEvent) {
    e.preventDefault();
    sendQuery(query.trim());
  }

  // "Chat about this" — the side panel's chunk previews are a raw peek
  // at what got stored, not an actual answer; this runs the node's
  // title through the exact same real retrieval+generation path typing
  // a question does (sendQuery), it's just a pre-filled question rather
  // than user-typed text.
  function handleChatAboutNode(node: GraphNode) {
    setSelectedNodeId(null);
    setSatellites([]);
    sendQuery(`Tell me about "${node.title}".`);
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

  // Stage 7.10 — real markdown via AnswerMarkdown, not a plain-text
  // <span>. While streaming, citation events (the only source of truth
  // for which markers are real) haven't all arrived yet, so `citations`
  // is passed empty — every marker disappears rather than resolving,
  // same "can't resolve yet" reasoning the old stripCitationMarkers
  // path used, but markdown formatting (lists, emphasis) still renders
  // live either way. Once done, markers resolve against the real
  // citations collected during the stream; clicking one selects that
  // node on the graph, same as clicking it directly.
  function renderAnswer() {
    if (!answer) {
      if (!streaming) return null;
      // Stage 7.11 — a plain "…" never changed, so a slow turn looked
      // exactly like a frozen one. Once at least one heartbeat has
      // arrived, switch to explicit "Thinking" copy with a dot count
      // tied to heartbeatCount, so the UI visibly reflects each
      // heartbeat instead of just sitting there.
      if (heartbeatCount === 0) return "…";
      return `Thinking${".".repeat((heartbeatCount % 3) + 1)}`;
    }
    return (
      <AnswerMarkdown
        text={answer}
        citations={streaming ? [] : citations}
        citeChipClassName={styles.citeChip}
        citeChipTitle={(_citation, index) => `Jump to source ${index + 1}`}
        onCiteClick={(citation) => handleNodeClick(citation.document_id)}
      />
    );
  }

  return (
    <AppShell userEmail={email}>
    <div className={styles.page}>
      <div className={styles.canvasWrap}>
        <GraphCanvas
          nodes={nodes}
          edges={edges}
          associativeEdges={associativeEdges}
          selectedNodeId={selectedNodeId}
          satellites={satellites}
          onNodeClick={handleNodeClick}
          pulse={pulse}
        />
      </div>

      <span className={styles.docsLink} onClick={() => router.push("/documents")}>
        Documents
      </span>

      {loadingGraph ? (
        <div className={styles.emptyState}>
          <p style={{ margin: 0 }}>Loading your graph…</p>
        </div>
      ) : (
        nodes.length === 0 && (
          <div className={styles.emptyState}>
            <p style={{ margin: 0 }}>Your graph will start forming as soon as it lands.</p>
            <button className={styles.emptyStateCta} onClick={() => router.push("/documents")}>
              Upload your first document
            </button>
          </div>
        )
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
          <div className={styles.sidePanelMeta}>
            <span className={styles.metaBadge}>
              {selectedNode.mime?.startsWith("image/") ? "Image" : "Document"}
            </span>
            {selectedNode.status === "sealed" && (
              <span className={`${styles.metaBadge} ${styles.metaBadgeSealed}`}>Sealed</span>
            )}
          </div>
          <div className={styles.sidePanelActions}>
            <button
              className={styles.sidePanelActionBtn}
              disabled={streaming}
              onClick={() => handleChatAboutNode(selectedNode)}
            >
              Chat about this
            </button>
            <button
              className={styles.sidePanelActionBtn}
              onClick={() => router.push("/documents")}
            >
              Open in Documents
            </button>
          </div>
          {selectedNode.status === "sealed" ? (
            <p className={styles.chunkItem}>
              This document is sealed — its content is hidden until you unlock it from
              Documents.
            </p>
          ) : (
            <>
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
            </>
          )}
        </div>
      )}

      {legendOpen && (
        <div className={styles.legend}>
          <div>node color = type</div>
          <div style={{ marginTop: 4 }}>
            <span style={{ color: "#8b5cf6" }}>●</span> document
            {"  "}
            <span style={{ color: "#2dd4bf" }}>●</span> image
            {"  "}
            <span style={{ color: "#f59e0b" }}>●</span> sealed
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
            ref={sessionsButtonRef}
            type="button"
            className={styles.sessionsButton}
            onClick={openSessionList}
            aria-label="Past conversations"
            disabled={replaying}
          >
            {replaying ? "replaying…" : "history"}
          </button>
          <input
            ref={chatInputRef}
            className={styles.chatInput}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask about your documents… (/ to focus)"
            disabled={streaming}
          />
          <button type="submit" className={styles.chatSend} disabled={streaming}>
            {streaming ? "…" : "Ask"}
          </button>
        </form>

        {sessionsOpen && (
          <div ref={sessionsPanelRef} className={styles.sessionsPanel}>
            {sessions.length === 0 && (
              <p className={styles.chunkItem}>No past conversations yet.</p>
            )}
            {sessions.map((s) => (
              <div key={s.id} className={styles.sessionItem}>
                <button
                  className={styles.sessionItemMain}
                  onClick={() => replaySession(s.id)}
                >
                  {new Date(s.created_at).toLocaleString()}
                </button>
                <span
                  className={styles.sessionItemLink}
                  onClick={() => router.push(`/chat?session=${s.id}`)}
                >
                  Open full conversation →
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
    </AppShell>
  );
}

export default function GraphPage() {
  return (
    <Suspense fallback={null}>
      <GraphPageInner />
    </Suspense>
  );
}
