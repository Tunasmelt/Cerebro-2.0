"use client";

import { useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import { authedFetch } from "@/lib/api";
import { useAuthedUser } from "@/lib/useAuthedUser";
import styles from "./playground.module.css";

// Stage 4.4 built the read-only breakdown for a past turn. Stage 5.6
// adds the deferred half of the mockup: editable sections, live
// client-side recalc (same len/4 estimate the mockup itself used), and
// a real "Run" that hits a dedicated generation entry point
// (POST .../playground/run) — never the normal chat path, and nothing
// about an edited run is persisted.

const INPUT_PRICE_PER_TOKEN_USD = 0.3 / 1_000_000;

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
type RunResult = {
  model: string;
  response: { content: string; tokens: number };
  total_tokens: number;
  estimated_cost_usd: number;
  latency_ms: number;
};

type EditableSection = {
  label: string;
  chunkId: string;
  citation: string | null;
  original: string;
  content: string;
};

const SECTION_TITLES: Record<string, string> = {
  system_instructions: "System instructions",
  context: "Context",
  user_query: "User query",
};

function estimateTokens(text: string): number {
  return Math.max(1, Math.round(text.length / 4));
}

export default function PlaygroundPage() {
  const { checking, email } = useAuthedUser();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [breakdown, setBreakdown] = useState<Breakdown | null>(null);
  const [loadingBreakdown, setLoadingBreakdown] = useState(false);

  const [sections, setSections] = useState<EditableSection[]>([]);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

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
      setSections([]);
      return;
    }
    setLoadingBreakdown(true);
    setRunResult(null);
    setRunError(null);
    authedFetch(`/api/chat/sessions/${selectedSessionId}/messages/${selectedMessageId}/prompt`)
      .then((res) => res.json())
      .then((body) => {
        if (body.error) {
          setBreakdown(null);
          setSections([]);
          return;
        }
        setBreakdown(body);
        setSections(
          body.sections.map((s: Section, i: number) => ({
            label: s.label,
            chunkId: s.citation ? `chunk_${i}` : "edited",
            citation: s.citation,
            original: s.content,
            content: s.content,
          }))
        );
      })
      .finally(() => setLoadingBreakdown(false));
  }, [selectedSessionId, selectedMessageId]);

  if (checking) return null;

  const assistantMessages = messages.filter((m) => m.role === "assistant");

  const totalTokens = sections.reduce((sum, s) => sum + estimateTokens(s.content), 0);
  const estCost = totalTokens * INPUT_PRICE_PER_TOKEN_USD;
  const estLatencyMs = Math.round(300 + totalTokens * 1.1);

  function updateSection(index: number, content: string) {
    setSections((prev) => prev.map((s, i) => (i === index ? { ...s, content } : s)));
  }

  function resetSection(index: number) {
    setSections((prev) => prev.map((s, i) => (i === index ? { ...s, content: s.original } : s)));
  }

  function resetAll() {
    setSections((prev) => prev.map((s) => ({ ...s, content: s.original })));
  }

  async function run() {
    if (!selectedSessionId) return;
    setRunning(true);
    setRunError(null);
    try {
      const systemInstructions =
        sections.find((s) => s.label === "system_instructions")?.content ?? "";
      const contextSections = sections
        .filter((s) => s.label === "context")
        .map((s) => ({ chunk_id: s.chunkId, content: s.content }));
      const userQuery = sections.find((s) => s.label === "user_query")?.content ?? "";

      const res = await authedFetch(`/api/chat/sessions/${selectedSessionId}/playground/run`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          system_instructions: systemInstructions,
          context_sections: contextSections,
          user_query: userQuery,
        }),
      });
      const body = await res.json();
      if (!res.ok) {
        setRunError(body.error?.message ?? "Run failed");
        return;
      }
      setRunResult(body);
    } finally {
      setRunning(false);
    }
  }

  return (
    <AppShell userEmail={email}>
      <div className={styles.page}>
        <div className={styles.pageHeader}>
          <h1>Playground</h1>
          <span className={styles.subtitle}>
            Edit the prompt that was actually sent, then run it for real.
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
            Pick a session and a turn above to edit and re-run its prompt.
          </div>
        )}

        {!loadingBreakdown && breakdown && (
          <div className={styles.shell}>
            <div className={styles.left}>
              <button className={styles.picker} onClick={resetAll} type="button">
                Reset to original
              </button>
              {sections.map((section, i) => (
                <div className={styles.section} key={i}>
                  <div className={styles.sectionHead}>
                    <span className={styles.sectionLabel}>
                      {SECTION_TITLES[section.label] ?? section.label}
                    </span>
                    {section.citation && (
                      <span className={styles.sectionCitation}>{section.citation}</span>
                    )}
                    <span className={styles.sectionTokens}>
                      {estimateTokens(section.content)} tok
                    </span>
                    {section.content !== section.original && (
                      <button
                        className={styles.sectionTokens}
                        onClick={() => resetSection(i)}
                        type="button"
                      >
                        reset
                      </button>
                    )}
                  </div>
                  <textarea
                    className={styles.sectionBody}
                    value={section.content}
                    onChange={(e) => updateSection(i, e.target.value)}
                    rows={Math.max(3, Math.ceil(section.content.length / 80))}
                  />
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
                <span className={styles.statValue}>{totalTokens}</span>
              </div>
              <div className={styles.statDivider} />
              <div className={styles.statBlock}>
                <span className={styles.statLabel}>Est. cost (input)</span>
                <span className={`${styles.statValue} ${styles.statCost}`}>
                  ${estCost.toFixed(6)}
                </span>
              </div>
              <div className={styles.statDivider} />
              <div className={styles.statBlock}>
                <span className={styles.statLabel}>Est. latency</span>
                <span className={styles.statValue}>~{estLatencyMs}ms</span>
              </div>
              <div className={styles.statDivider} />

              <button
                className={styles.picker}
                onClick={run}
                disabled={running}
                type="button"
              >
                {running ? "Running…" : "Run"}
              </button>

              {runError && <div className={styles.emptyState}>{runError}</div>}

              <div className={styles.responseBlock}>
                <span className={styles.responseLabel}>
                  {runResult
                    ? `Response (${runResult.response.tokens} tok, ${runResult.latency_ms}ms, $${runResult.estimated_cost_usd.toFixed(6)})`
                    : "Response"}
                </span>
                <div className={styles.responseText}>
                  {runResult
                    ? runResult.response.content
                    : "Run the edited prompt to see a real response here."}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
