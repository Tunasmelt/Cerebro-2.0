"use client";

import { useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import { authedFetch } from "@/lib/api";
import { useAuthedUser } from "@/lib/useAuthedUser";
import styles from "./playground.module.css";

// Stage 4.4 — read-only token/cost breakdown for a past chat turn.
// Deliberately not the mockup's editable-textarea/re-run flow (Stage
// 4.4's own note: that's deferred to a future Phase 5 stage, needing
// its own generation entry point). This shows what was actually sent,
// reconstructed server-side — nothing here is editable or re-runnable.

type Session = { id: string; created_at: string };
type Message = { id: string; role: string; content: string; created_at: string };
type Section = { label: string; content: string; tokens: number; citation: string | null };
type Breakdown = {
  model: string;
  sections: Section[];
  response: { content: string; tokens: number };
  total_tokens: number;
  estimated_cost_usd: number;
};

const SECTION_TITLES: Record<string, string> = {
  system_instructions: "System instructions",
  context: "Context",
  user_query: "User query",
};

export default function PlaygroundPage() {
  const { checking, email } = useAuthedUser();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [breakdown, setBreakdown] = useState<Breakdown | null>(null);
  const [loadingBreakdown, setLoadingBreakdown] = useState(false);

  useEffect(() => {
    if (checking) return;
    authedFetch("/api/chat/sessions")
      .then((res) => res.json())
      .then((body) => setSessions(body.sessions ?? []));
  }, [checking]);

  useEffect(() => {
    if (!selectedSessionId) {
      setMessages([]);
      return;
    }
    authedFetch(`/api/chat/sessions/${selectedSessionId}/messages`)
      .then((res) => res.json())
      .then((body) => setMessages(body.messages ?? []));
  }, [selectedSessionId]);

  useEffect(() => {
    if (!selectedSessionId || !selectedMessageId) {
      setBreakdown(null);
      return;
    }
    setLoadingBreakdown(true);
    authedFetch(`/api/chat/sessions/${selectedSessionId}/messages/${selectedMessageId}/prompt`)
      .then((res) => res.json())
      .then((body) => setBreakdown(body.error ? null : body))
      .finally(() => setLoadingBreakdown(false));
  }, [selectedSessionId, selectedMessageId]);

  if (checking) return null;

  const assistantMessages = messages.filter((m) => m.role === "assistant");

  return (
    <AppShell userEmail={email}>
      <div className={styles.page}>
        <div className={styles.pageHeader}>
          <h1>Playground</h1>
          <span className={styles.subtitle}>
            Read-only — shows the prompt actually sent for a past turn.
          </span>
        </div>

        <div className={styles.pickerRow}>
          <select
            className={styles.picker}
            value={selectedSessionId ?? ""}
            onChange={(e) => {
              setSelectedSessionId(e.target.value || null);
              setSelectedMessageId(null);
            }}
          >
            <option value="">Select a chat session…</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {new Date(s.created_at).toLocaleString()}
              </option>
            ))}
          </select>

          <select
            className={styles.picker}
            value={selectedMessageId ?? ""}
            onChange={(e) => setSelectedMessageId(e.target.value || null)}
            disabled={assistantMessages.length === 0}
          >
            <option value="">Select a turn…</option>
            {assistantMessages.map((m) => (
              <option key={m.id} value={m.id}>
                {m.content.slice(0, 60)}
              </option>
            ))}
          </select>
        </div>

        {loadingBreakdown && <div className={styles.emptyState}>Loading…</div>}

        {!loadingBreakdown && !breakdown && (
          <div className={styles.emptyState}>
            Pick a session and a turn above to see its token/cost breakdown.
          </div>
        )}

        {!loadingBreakdown && breakdown && (
          <div className={styles.shell}>
            <div className={styles.left}>
              {breakdown.sections.map((section, i) => (
                <div className={styles.section} key={i}>
                  <div className={styles.sectionHead}>
                    <span className={styles.sectionLabel}>
                      {SECTION_TITLES[section.label] ?? section.label}
                    </span>
                    {section.citation && (
                      <span className={styles.sectionCitation}>{section.citation}</span>
                    )}
                    <span className={styles.sectionTokens}>{section.tokens} tok</span>
                  </div>
                  <div className={styles.sectionBody}>{section.content}</div>
                </div>
              ))}
            </div>

            <div className={styles.right}>
              <div className={styles.statBlock}>
                <span className={styles.statLabel}>Model</span>
                <span className={styles.statValue}>{breakdown.model}</span>
              </div>
              <div className={styles.statDivider} />
              <div className={styles.statBlock}>
                <span className={styles.statLabel}>Total tokens (est.)</span>
                <span className={styles.statValue}>{breakdown.total_tokens}</span>
              </div>
              <div className={styles.statDivider} />
              <div className={styles.statBlock}>
                <span className={`${styles.statValue} ${styles.statCost}`}>
                  ${breakdown.estimated_cost_usd.toFixed(6)}
                </span>
                <span className={styles.statLabel}>Est. cost</span>
              </div>
              <div className={styles.statDivider} />

              <div className={styles.responseBlock}>
                <span className={styles.responseLabel}>
                  Response ({breakdown.response.tokens} tok)
                </span>
                <div className={styles.responseText}>{breakdown.response.content}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
