"use client";

import { useEffect } from "react";

import styles from "./ConfirmModal.module.css";

// Replaces the browser's native window.confirm()/alert() — those render
// as an unstyled "<site> says" box the user can't theme or style, the
// exact thing flagged live on /chat's delete-conversation flow (and
// /documents' View-error path used a bare alert() for the same reason).
// One shared component instead of every page re-copying the same
// overlay/modal CSS (documents/page.tsx had already done this once,
// independently, before this existed).
export interface ConfirmModalProps {
  title: string;
  body: React.ReactNode;
  confirmLabel: string;
  // Omit for an alert-style dialog (a single acknowledgement button,
  // no cancel) — the documents/page.tsx "Could not open this document"
  // case, which never had a real choice to confirm.
  cancelLabel?: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  title,
  body,
  confirmLabel,
  cancelLabel,
  danger,
  loading,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && !loading) onCancel();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [loading, onCancel]);

  return (
    <div className={styles.overlay} onClick={() => !loading && onCancel()}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <h2 className={styles.title}>{title}</h2>
        <div className={styles.body}>{body}</div>
        <div className={styles.actions}>
          {cancelLabel && (
            <button className={styles.btn} disabled={loading} onClick={onCancel}>
              {cancelLabel}
            </button>
          )}
          <button
            className={`${styles.btn} ${danger ? styles.btnDanger : styles.btnPrimary}`}
            disabled={loading}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
