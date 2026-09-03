"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import { authedFetch } from "@/lib/api";
import { parseAnswerSegments } from "@/lib/graph/citations";
import type { ChatMessage, ChatSession } from "@/lib/graph/types";
import { useAuthedUser } from "@/lib/useAuthedUser";
import styles from "./chat.module.css";

// Chat management pass — a real page for viewing/deleting/exporting a
// past conversation, something no page did before (the /graph chat dock
// only ever replays a graph pulse, see that page's own sessions panel).
// Reuses parseAnswerSegments (lib/graph/citations.ts) exactly as /graph
// does for a live turn — the only thing that's new is feeding it a
// message's real, backend-resolved `citations` array (services/api's
// chat/storage.py get_messages) instead of live SSE state, which is
// what actually makes a reopened conversation's citation chips work at
// all.

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function exportMarkdown(session: ChatSession, messages: ChatMessage[]): string {
  const lines: string[] = [`# Chat — ${formatDate(session.created_at)}`, ""];
  const allCitations = new Map<string, string>();

  for (const m of messages) {
    lines.push(m.role === "user" ? "## You" : "## Cerebro");
    let text = m.content;
    for (const c of m.citations ?? []) {
      allCitations.set(c.chunk_id, c.document_title);
    }
    // Resolve [[chunk:id]] markers to a plain [n] footnote style, in
    // whatever order they appear in this message specifically.
    const segments = parseAnswerSegments(text);
    text = segments
      .map((seg) => {
        if (seg.type === "text") return seg.text;
        const citation = (m.citations ?? []).find((c) => c.chunk_id === seg.chunkId);
        if (!citation) return "";
        const index = [...allCitations.keys()].indexOf(citation.chunk_id) + 1;
        return `[${index}]`;
      })
      .join("");
    lines.push(text.trim(), "");
  }

  if (allCitations.size > 0) {
    lines.push("---", "", "**Sources**", "");
    [...allCitations.entries()].forEach(([, title], i) => {
      lines.push(`[${i + 1}]: ${title}`);
    });
  }

  return lines.join("\n");
}

function downloadFile(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function ChatPageInner() {
  const { checking, email } = useAuthedUser();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    const res = await authedFetch("/api/chat/sessions");
    const body = await res.json();
    setSessions(body.sessions ?? []);
  }, []);

  useEffect(() => {
    if (checking) return;
    fetchSessions();
  }, [checking, fetchSessions]);

  // A cross-page link (e.g. /graph's "Open full conversation") lands
  // here with ?session=<id> — select it once sessions are in.
  useEffect(() => {
    const fromQuery = searchParams.get("session");
    if (fromQuery && !selectedId) setSelectedId(fromQuery);
  }, [searchParams, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setMessages([]);
      return;
    }
    setLoadingMessages(true);
    authedFetch(`/api/chat/sessions/${selectedId}/messages`)
      .then((res) => res.json())
      .then((body) => setMessages(body.messages ?? []))
      .finally(() => setLoadingMessages(false));
  }, [selectedId]);

  async function handleDelete(session: ChatSession, e: React.MouseEvent) {
    e.stopPropagation();
    if (!window.confirm("Delete this conversation? This can't be undone.")) return;
    setDeletingId(session.id);
    try {
      await authedFetch(`/api/chat/sessions/${session.id}`, { method: "DELETE" });
      setSessions((prev) => prev.filter((s) => s.id !== session.id));
      if (selectedId === session.id) setSelectedId(null);
    } finally {
      setDeletingId(null);
    }
  }

  async function handleExport(session: ChatSession, e: React.MouseEvent) {
    e.stopPropagation();
    const res = await authedFetch(`/api/chat/sessions/${session.id}/messages`);
    const body = await res.json();
    const msgs: ChatMessage[] = body.messages ?? [];
    downloadFile(`cerebro-chat-${session.id.slice(0, 8)}.md`, exportMarkdown(session, msgs));
  }

  function renderMessageText(m: ChatMessage) {
    const citations = m.citations ?? [];
    const segments = parseAnswerSegments(m.content);
    return segments.map((seg, i) => {
      if (seg.type === "text") return <span key={i}>{seg.text}</span>;
      // A marker naming a chunk id outside the message's own resolved
      // citations (hallucinated, or dropped server-side) never becomes
      // a chip — same distrust-by-default posture /graph's live chat
      // already applies.
      const citeIndex = citations.findIndex((c) => c.chunk_id === seg.chunkId);
      if (citeIndex === -1) return null;
      const citation = citations[citeIndex];
      return (
        <button
          key={i}
          type="button"
          className={styles.citeChip}
          title={citation.document_title}
          onClick={() => router.push(`/graph?focus=${citation.document_id}`)}
        >
          {citeIndex + 1}
        </button>
      );
    });
  }

  if (checking) return null;

  const selectedSession = sessions.find((s) => s.id === selectedId) ?? null;

  return (
    <AppShell userEmail={email}>
      <div className={styles.shell}>
        <div className={styles.sessionList}>
          <div className={styles.sessionListHeader}>Chats</div>
          {sessions.length === 0 && (
            <div className={styles.emptyState}>
              No conversations yet — ask something from the Brain page.
            </div>
          )}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`${styles.sessionRow} ${s.id === selectedId ? styles.sessionRowActive : ""}`}
              onClick={() => setSelectedId(s.id)}
            >
              <div className={styles.sessionRowMain}>
                <div className={styles.sessionPreview}>{s.preview || "New conversation"}</div>
                <div className={styles.sessionDate}>{formatDate(s.created_at)}</div>
              </div>
              <div className={styles.sessionRowActions}>
                <button
                  className={styles.iconBtn}
                  title="Export"
                  onClick={(e) => handleExport(s, e)}
                >
                  ↓
                </button>
                <button
                  className={styles.iconBtn}
                  title="Delete"
                  disabled={deletingId === s.id}
                  onClick={(e) => handleDelete(s, e)}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className={styles.transcript}>
          {!selectedSession && (
            <div className={styles.emptyState}>Select a conversation to view it.</div>
          )}
          {selectedSession && loadingMessages && (
            <div className={styles.emptyState}>Loading…</div>
          )}
          {selectedSession && !loadingMessages && (
            <>
              <div className={styles.transcriptHeader}>
                <span>{formatDate(selectedSession.created_at)}</span>
                <button
                  className={styles.exportBtn}
                  onClick={(e) => handleExport(selectedSession, e)}
                >
                  Export
                </button>
              </div>
              <div className={styles.messages}>
                {messages.map((m) => (
                  <div
                    key={m.id}
                    className={`${styles.messageRow} ${m.role === "user" ? styles.messageUser : styles.messageAssistant}`}
                  >
                    <div className={styles.messageBubble}>{renderMessageText(m)}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <ChatPageInner />
    </Suspense>
  );
}
