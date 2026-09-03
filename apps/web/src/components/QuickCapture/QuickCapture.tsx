"use client";

import { useRef, useState } from "react";

import { authedFetch } from "@/lib/api";
import styles from "./QuickCapture.module.css";

// Stage 5.5 — a persistent, always-available quick-capture affordance,
// mounted once in AppShell's topbar so it's on every authenticated page
// (Brain, Documents, Kanban, Tasks, Playground, Settings), not buried
// in the Documents upload flow. Feeds POST /documents/capture, which
// runs the captured text through the same extract -> embed pipeline
// every uploaded document goes through — this widget's only job is
// getting a thought in fast, not a second ingest UI.

const MAX_CAPTURE_CHARS = 20_000; // mirrors documents_storage.py's
// MAX_CAPTURE_CHARS — client-side feedback only, the server is the
// real enforcement.

type Status = "idle" | "sending" | "done" | "error";

export default function QuickCapture() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function openPopover() {
    setOpen(true);
    setStatus("idle");
    setErrorMessage(null);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function close() {
    setOpen(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || status === "sending") return;

    setStatus("sending");
    setErrorMessage(null);
    try {
      const res = await authedFetch("/api/documents/capture", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: trimmed }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.error?.message || "Capture failed");
      }
      setStatus("done");
      setText("");
      setTimeout(() => setOpen(false), 900);
    } catch (err) {
      setStatus("error");
      setErrorMessage(err instanceof Error ? err.message : "Capture failed");
    }
  }

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={styles.trigger}
        onClick={open ? close : openPopover}
        aria-label="Quick capture"
        title="Quick capture"
      >
        +
      </button>

      {open && (
        <>
          <div className={styles.backdrop} onClick={close} />
          <form className={styles.popover} onSubmit={handleSubmit}>
            <textarea
              ref={textareaRef}
              className={styles.textarea}
              placeholder="Capture a thought…"
              value={text}
              maxLength={MAX_CAPTURE_CHARS}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit(e);
                if (e.key === "Escape") close();
              }}
              disabled={status === "sending"}
            />
            <div className={styles.footer}>
              <span className={styles.hint}>
                {status === "done"
                  ? "Captured."
                  : status === "error"
                    ? errorMessage
                    : "⌘/Ctrl + Enter to save"}
              </span>
              <button
                type="submit"
                className={styles.saveBtn}
                disabled={!text.trim() || status === "sending"}
              >
                {status === "sending" ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
