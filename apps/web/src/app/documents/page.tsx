"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import AppShell from "@/components/AppShell";
import ConfirmModal from "@/components/ConfirmModal";
import { authedFetch } from "@/lib/api";
import { deriveKey, deriveKeyBytes, generateSalt, sealChunkWithKey } from "@/lib/crypto/seal";
import type { DocumentRow } from "@/lib/graph/types";
import { createClient } from "@/lib/supabase/client";
import { useAuthedUser } from "@/lib/useAuthedUser";
import styles from "./documents.module.css";

// Stage 3.2/3.3's client-side sealing was built and adversarially
// tested end to end, but no page ever actually exposed a way to
// trigger it — Stage 4.7's own notes flagged this as a real, separate
// gap ("Documents still doesn't have one either"), never closed.
function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

// Mirrors services/api/app/core/documents_storage.py's ALLOWED_MIME_TYPES —
// fast client-side feedback only, Supabase Storage's bucket policy is the
// real enforcement boundary (see that module's docstring).
const ALLOWED_MIME_TYPES: Record<string, string> = {
  "text/plain": "TXT",
  "text/markdown": "MD",
  "application/pdf": "PDF",
  "image/jpeg": "JPG",
  "image/png": "PNG",
  "image/webp": "WEBP",
};
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

// Poll the document list while anything is still processing, so a
// status flip (processing -> ready/failed) shows up without a reload —
// same "no live update" gap flagged for /graph, closed here for /documents.
const POLL_INTERVAL_MS = 3000;

type UploadStage = "uploading" | "confirming" | "failed";

type UploadItem = {
  key: string;
  filename: string;
  stage: UploadStage;
  error?: string;
};

// Stage 4.6 — candidates are ephemeral (never persisted server-side);
// confirming one is a normal card create against whichever board this
// page lazily creates/reuses on first confirm, same "no board is ever
// silently populated" posture the backend's own docstring establishes —
// nothing is added until the user explicitly clicks "Add".
type ActionItemCandidate = {
  title: string;
  description: string;
  source_chunk_id: string;
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}b`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}kb`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}mb`;
}

function typeLabel(mime: string): string {
  return ALLOWED_MIME_TYPES[mime] ?? mime.split("/")[1]?.toUpperCase() ?? "FILE";
}

// Compact icon buttons for the actions column — text-label buttons
// ("Extract action items", "Retry", …) wrapped unpredictably across two
// ragged rows once a document had more than two available actions (see
// the messy multi-row layout this replaced). Icons at a fixed 28px each
// fit every action in one row on both desktop and mobile, with the
// action name preserved as a title/aria-label tooltip.
const ACTION_ICONS: Record<string, React.ReactNode> = {
  retry: (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M11.5 7A4.5 4.5 0 1 1 9.8 3.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      <path d="M9.2 2.2L9.8 3.9L8 4.3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  extract: (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M2.5 4.3L3.3 5.1L5 3.3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6.5 4H11.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      <path d="M2.5 8.3L3.3 9.1L5 7.3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6.5 8H11.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  ),
  seal: (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="3" y="6.5" width="8" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.2" />
      <path d="M4.5 6.5V4.5a2.5 2.5 0 0 1 5 0V6.5" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  unlock: (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="3" y="6.5" width="8" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.2" />
      <path d="M4.5 6.5V4.5a2.5 2.5 0 0 1 5 0" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
  view: (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M1.5 7S3.8 3 7 3s5.5 4 5.5 4-2.3 4-5.5 4S1.5 7 1.5 7Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      <circle cx="7" cy="7" r="1.6" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  delete: (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path
        d="M2.5 3.5H11.5M5.2 3.5V2.3a.8.8 0 0 1 .8-.8h2a.8.8 0 0 1 .8.8V3.5M4.5 3.5V11a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1V3.5"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  ),
};

export default function DocumentsPage() {
  const { checking, email } = useAuthedUser();
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [extractingId, setExtractingId] = useState<string | null>(null);
  const [actionItems, setActionItems] = useState<Record<string, ActionItemCandidate[]>>({});
  const [addedChunkIds, setAddedChunkIds] = useState<Set<string>>(new Set());
  const defaultBoardId = useRef<string | null>(null);

  const [sealPromptFor, setSealPromptFor] = useState<string | null>(null);
  const [sealPassphrase, setSealPassphrase] = useState("");
  const [sealing, setSealing] = useState(false);
  const [sealError, setSealError] = useState<string | null>(null);

  const [unlockPromptFor, setUnlockPromptFor] = useState<string | null>(null);
  const [unlockPassphrase, setUnlockPassphrase] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const [unlockError, setUnlockError] = useState<string | null>(null);
  // Decrypted content lives only in memory, keyed by document id, never
  // written anywhere else — closing it (closeUnsealedContent) is the
  // only way it goes away, same "never persisted" posture as the
  // passphrase-derived key itself.
  const [unsealedContent, setUnsealedContent] = useState<
    Record<string, { ordinal: number; content: string }[]>
  >({});

  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deletePromptFor, setDeletePromptFor] = useState<DocumentRow | null>(null);
  const [viewingId, setViewingId] = useState<string | null>(null);
  const [viewErrorMessage, setViewErrorMessage] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);

  // Distinguishes "still loading" and "failed to load" from "genuinely
  // no documents yet" — without these the table silently showed the
  // upload-a-document empty state both while loading and when a fetch
  // actually failed, with no way to tell the difference or retry.
  const [loadingDocuments, setLoadingDocuments] = useState(true);
  const [documentsLoadError, setDocumentsLoadError] = useState(false);

  const fetchDocuments = useCallback(async () => {
    try {
      const res = await authedFetch("/api/documents");
      if (!res.ok) {
        setDocumentsLoadError(true);
        return;
      }
      const body = await res.json();
      setDocuments(body.documents ?? []);
      setDocumentsLoadError(false);
    } catch {
      setDocumentsLoadError(true);
    } finally {
      setLoadingDocuments(false);
    }
  }, []);

  useEffect(() => {
    if (checking) return;
    fetchDocuments();
  }, [checking, fetchDocuments]);

  useEffect(() => {
    if (checking) return;
    const hasProcessing = documents.some((d) => d.status === "processing");
    if (!hasProcessing && uploads.length === 0) return;
    const interval = setInterval(fetchDocuments, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [checking, documents, uploads.length, fetchDocuments]);

  async function uploadOne(file: File) {
    const key = `${file.name}-${Date.now()}`;
    setUploads((prev) => [...prev, { key, filename: file.name, stage: "uploading" }]);

    if (!ALLOWED_MIME_TYPES[file.type]) {
      setUploads((prev) =>
        prev.map((u) => (u.key === key ? { ...u, stage: "failed", error: `Unsupported file type: ${file.type || "unknown"}` } : u))
      );
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploads((prev) =>
        prev.map((u) => (u.key === key ? { ...u, stage: "failed", error: "File exceeds the 50MB upload limit" } : u))
      );
      return;
    }

    try {
      const initRes = await authedFetch("/api/documents", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ filename: file.name, mime: file.type, size_bytes: file.size }),
      });
      if (!initRes.ok) {
        const body = await initRes.json().catch(() => ({}));
        throw new Error(body?.error?.message || "Could not start the upload");
      }
      const { id, upload_url } = await initRes.json();

      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      const putRes = await fetch(upload_url, {
        method: "PUT",
        headers: {
          "content-type": file.type,
          apikey: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
          authorization: `Bearer ${session?.access_token}`,
        },
        body: file,
      });
      if (!putRes.ok) {
        throw new Error("Upload to storage failed");
      }

      setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, stage: "confirming" } : u)));

      const confirmRes = await authedFetch(`/api/documents/${id}/confirm`, { method: "POST" });
      if (!confirmRes.ok) {
        const body = await confirmRes.json().catch(() => ({}));
        throw new Error(body?.error?.message || "Could not confirm the upload");
      }

      // Success — drop the in-flight row, the real document now shows up
      // in the polled list below with its own processing badge.
      setUploads((prev) => prev.filter((u) => u.key !== key));
      fetchDocuments();
    } catch (err) {
      setUploads((prev) =>
        prev.map((u) =>
          u.key === key
            ? { ...u, stage: "failed", error: err instanceof Error ? err.message : "Upload failed" }
            : u
        )
      );
    }
  }

  function handleFiles(fileList: FileList | null) {
    if (!fileList) return;
    Array.from(fileList).forEach(uploadOne);
  }

  async function handleRetry(documentId: string) {
    setRetryingId(documentId);
    try {
      await authedFetch(`/api/documents/${documentId}/retry`, { method: "POST" });
      await fetchDocuments();
    } finally {
      setRetryingId(null);
    }
  }

  function dismissUpload(key: string) {
    setUploads((prev) => prev.filter((u) => u.key !== key));
  }

  async function handleView(doc: DocumentRow) {
    setViewingId(doc.id);
    // A tab opened only after the await below has resolved is no longer
    // inside the click's user-gesture window in most browsers — the
    // popup gets silently blocked, which is exactly what "View doesn't
    // work" looks like from the outside (no error, nothing happens).
    // Opening a blank tab synchronously here, then pointing it at the
    // real URL once it's fetched, keeps the whole thing inside the
    // gesture instead.
    //
    // Passing "noopener" (or "noreferrer", which implies it) to
    // window.open makes the browser return null instead of a usable
    // window reference — the new tab still opens, but this code has no
    // handle to set its location, so it silently fell through to the
    // same-tab fallback below and left the popup blank forever. Get a
    // real reference here, then null out its `opener` directly — same
    // reverse-tabnabbing protection, without losing control of the tab.
    const pending = window.open("", "_blank");
    if (pending) pending.opener = null;
    try {
      const res = await authedFetch(`/api/documents/${doc.id}/download`);
      const body = await res.json();
      if (!res.ok) {
        pending?.close();
        setViewErrorMessage(body?.error?.message || "Could not open this document");
        return;
      }
      if (pending) {
        pending.location.href = body.url;
      } else {
        // Popup blocked even for the synchronous open (e.g. a stricter
        // browser setting) — fall back to a same-tab navigation rather
        // than leaving the click with no visible effect at all.
        window.location.href = body.url;
      }
    } finally {
      setViewingId(null);
    }
  }

  function requestDelete(doc: DocumentRow) {
    setDeletePromptFor(doc);
  }

  async function confirmDelete() {
    const doc = deletePromptFor;
    if (!doc) return;
    setDeletingId(doc.id);
    try {
      await authedFetch(`/api/documents/${doc.id}`, { method: "DELETE" });
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    } finally {
      setDeletingId(null);
      setDeletePromptFor(null);
    }
  }

  function startRename(doc: DocumentRow) {
    setRenamingId(doc.id);
    setRenameValue(doc.title);
  }

  function cancelRename() {
    setRenamingId(null);
    setRenameValue("");
  }

  async function handleRenameSave(documentId: string) {
    const title = renameValue.trim();
    if (!title) return;
    setRenameSaving(true);
    try {
      const res = await authedFetch(`/api/documents/${documentId}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (res.ok) {
        setDocuments((prev) => prev.map((d) => (d.id === documentId ? { ...d, title } : d)));
        setRenamingId(null);
      }
    } finally {
      setRenameSaving(false);
    }
  }

  async function handleExtractActionItems(documentId: string) {
    setExtractingId(documentId);
    try {
      const res = await authedFetch(`/api/documents/${documentId}/extract-action-items`, {
        method: "POST",
      });
      const body = await res.json();
      setActionItems((prev) => ({ ...prev, [documentId]: res.ok ? (body.items ?? []) : [] }));
    } finally {
      setExtractingId(null);
    }
  }

  async function ensureDefaultBoardId(): Promise<string> {
    if (defaultBoardId.current) return defaultBoardId.current;
    const listRes = await authedFetch("/api/boards");
    const listBody = await listRes.json();
    const boards = listBody.boards ?? [];
    if (boards.length > 0) {
      defaultBoardId.current = boards[0].id;
      return boards[0].id;
    }
    const createRes = await authedFetch("/api/boards", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: "My Board" }),
    });
    const created = await createRes.json();
    defaultBoardId.current = created.id;
    return created.id;
  }

  async function handleConfirmActionItem(documentId: string, item: ActionItemCandidate) {
    const boardId = await ensureDefaultBoardId();
    await authedFetch(`/api/boards/${boardId}/cards`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        column_name: "Backlog",
        title: item.title,
        description: item.description,
        document_id: documentId,
      }),
    });
    setAddedChunkIds((prev) => new Set(prev).add(item.source_chunk_id));
  }

  function openSealPrompt(documentId: string) {
    setSealPromptFor(documentId);
    setSealPassphrase("");
    setSealError(null);
  }

  async function handleConfirmSeal(documentId: string) {
    const passphrase = sealPassphrase;
    if (!passphrase) return;
    setSealing(true);
    setSealError(null);
    try {
      const chunksRes = await authedFetch(`/api/graph/nodes/${documentId}/chunks`);
      if (!chunksRes.ok) throw new Error("Could not read this document's content");
      const chunksBody = await chunksRes.json();
      const chunks: { ordinal: number; content: string }[] = chunksBody.chunks ?? [];

      // One salt, derived once for the whole document — not once per
      // chunk. A real bug this fixed: calling sealBytes() independently
      // per chunk gave each one its own fresh salt and therefore its
      // own different derived key, even though they share one
      // passphrase, so the backend (which decrypts every chunk of a
      // document with one caller-supplied key) could only ever
      // correctly unseal a document's first chunk. One key reused with
      // a fresh nonce per chunk is the correct AES-GCM pattern, and the
      // one the unlock flow below actually depends on. The passphrase
      // itself never leaves this function, only the resulting
      // ciphertext (and the public, non-secret salt) does.
      const salt = generateSalt();
      const key = await deriveKey(passphrase, salt);
      const saltB64 = bytesToBase64(salt);
      const sealedChunks = await Promise.all(
        chunks.map(async (chunk) => {
          const payload = await sealChunkWithKey(new TextEncoder().encode(chunk.content), key);
          return {
            ordinal: chunk.ordinal,
            content_ciphertext: bytesToBase64(payload.ciphertext),
            salt: saltB64,
            nonce: bytesToBase64(payload.nonce),
          };
        })
      );

      const sealRes = await authedFetch(`/api/documents/${documentId}/seal`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ chunks: sealedChunks }),
      });
      if (!sealRes.ok) {
        const body = await sealRes.json().catch(() => ({}));
        throw new Error(
          body?.error?.code === "not_ready"
            ? "This document is still processing — try again once it's ready."
            : body?.error?.message || "Could not seal this document"
        );
      }

      setSealPromptFor(null);
      setSealPassphrase("");
      await fetchDocuments();
    } catch (err) {
      setSealError(err instanceof Error ? err.message : "Could not seal this document");
    } finally {
      setSealing(false);
    }
  }

  function openUnlockPrompt(documentId: string) {
    setUnlockPromptFor(documentId);
    setUnlockPassphrase("");
    setUnlockError(null);
  }

  // Unlock is a three-step round trip, per Stage 3.3's design: (1) fetch
  // the document's salt (not secret — needed just to re-derive the
  // exact key it was sealed with), (2) POST /unlock, which server-side
  // test-decrypts one real chunk against the derived key and — only if
  // that succeeds — issues a short-lived (15min) claim scoped to this
  // document, (3) POST /unseal with that claim + the same key, which
  // decrypts and returns every chunk. The derived key transits the
  // server on steps 2/3 by design (see CLAUDE.md's naming-discipline
  // note: this is "passphrase-gated," deliberately never called
  // "zero-knowledge") — never stored, never sent anywhere else, and
  // never persisted client-side either; closing the view is what clears
  // it from this page's own memory.
  async function handleConfirmUnlock(documentId: string) {
    const passphrase = unlockPassphrase;
    if (!passphrase) return;
    setUnlocking(true);
    setUnlockError(null);
    try {
      const saltRes = await authedFetch(`/api/documents/${documentId}/seal-salt`);
      if (!saltRes.ok) {
        const body = await saltRes.json().catch(() => ({}));
        throw new Error(body?.error?.message || "Could not find sealed content for this document");
      }
      const { salt } = await saltRes.json();
      const keyBytes = await deriveKeyBytes(passphrase, base64ToBytes(salt));
      const keyB64 = bytesToBase64(keyBytes);

      const unlockRes = await authedFetch(`/api/documents/${documentId}/unlock`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ key: keyB64 }),
      });
      if (!unlockRes.ok) {
        const body = await unlockRes.json().catch(() => ({}));
        throw new Error(
          body?.error?.code === "invalid_key"
            ? "Incorrect passphrase"
            : body?.error?.message || "Could not unlock this document"
        );
      }
      const { claim_id: claimId } = await unlockRes.json();

      const unsealRes = await authedFetch(`/api/documents/${documentId}/unseal`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ claim_id: claimId, key: keyB64 }),
      });
      if (!unsealRes.ok) {
        const body = await unsealRes.json().catch(() => ({}));
        throw new Error(body?.error?.message || "Could not decrypt this document");
      }
      const unsealBody = await unsealRes.json();

      setUnsealedContent((prev) => ({ ...prev, [documentId]: unsealBody.chunks ?? [] }));
      setUnlockPromptFor(null);
      setUnlockPassphrase("");
    } catch (err) {
      setUnlockError(err instanceof Error ? err.message : "Could not unlock this document");
    } finally {
      setUnlocking(false);
    }
  }

  function closeUnsealedContent(documentId: string) {
    setUnsealedContent((prev) => {
      const next = { ...prev };
      delete next[documentId];
      return next;
    });
  }

  function handleDeclineActionItem(documentId: string, item: ActionItemCandidate) {
    setActionItems((prev) => ({
      ...prev,
      [documentId]: (prev[documentId] ?? []).filter(
        (c) => c.source_chunk_id !== item.source_chunk_id
      ),
    }));
  }

  if (checking) return null;

  return (
    <AppShell userEmail={email}>
    <div className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1>Documents</h1>
        </div>

        <div
          className={`${styles.dropzone} ${dragging ? styles.drag : ""}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            handleFiles(e.dataTransfer.files);
          }}
        >
          <p>Drag files here, or click to browse</p>
          <span className={styles.hint}>PDF, images, plain text, markdown — up to 50MB</span>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={`${Object.keys(ALLOWED_MIME_TYPES).join(",")},.md`}
            style={{ display: "none" }}
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {uploads.length > 0 && (
          <div className={styles.uploadList}>
            {uploads.map((u) => (
              <div key={u.key} className={`${styles.uploadRow} ${u.stage === "failed" ? styles.failed : ""}`}>
                <div className={styles.uploadFilename}>{u.filename}</div>
                <div className={styles.uploadTrack}>
                  <div
                    className={`${styles.uploadFill} ${u.stage === "failed" ? styles.failed : ""}`}
                    style={{ width: u.stage === "uploading" ? "40%" : u.stage === "confirming" ? "80%" : "100%" }}
                  />
                </div>
                <div className={styles.uploadStage}>
                  {u.stage === "uploading" ? "Uploading" : u.stage === "confirming" ? "Confirming" : "Failed"}
                </div>
                {u.stage === "failed" && (
                  <div className={styles.uploadErrorRow}>
                    <span className={styles.uploadErrorMsg}>{u.error}</span>
                    <button className={styles.retryBtn} onClick={() => dismissUpload(u.key)}>
                      Dismiss
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className={styles.tableCard}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Title</th>
              <th>Size</th>
              <th>Uploaded</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loadingDocuments ? (
              <tr>
                <td colSpan={5} className={styles.emptyRow}>
                  Loading documents…
                </td>
              </tr>
            ) : documentsLoadError ? (
              <tr>
                <td colSpan={5} className={styles.emptyRow}>
                  Couldn&apos;t load your documents.{" "}
                  <button className={styles.retryBtn} onClick={() => fetchDocuments()}>
                    Retry
                  </button>
                </td>
              </tr>
            ) : (
              documents.length === 0 && (
                <tr>
                  <td colSpan={5} className={styles.emptyRow}>
                    No documents yet — drag one in above.
                  </td>
                </tr>
              )
            )}
            {documents.map((doc, i) => (
              <Fragment key={doc.id}>
                <tr style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}>
                  <td>
                    <div className={styles.titleCell}>
                      <div className={styles.typeIcon}>{typeLabel(doc.mime)}</div>
                      {renamingId === doc.id ? (
                        <>
                          <input
                            autoFocus
                            className={styles.titleInput}
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") handleRenameSave(doc.id);
                              if (e.key === "Escape") cancelRename();
                            }}
                            disabled={renameSaving}
                          />
                          <button
                            className={styles.titleEditBtn}
                            title="Save"
                            disabled={renameSaving || !renameValue.trim()}
                            onClick={() => handleRenameSave(doc.id)}
                          >
                            ✓
                          </button>
                          <button
                            className={styles.titleEditBtn}
                            title="Cancel"
                            disabled={renameSaving}
                            onClick={cancelRename}
                          >
                            ×
                          </button>
                        </>
                      ) : (
                        <>
                          <span className={styles.titleText}>{doc.title}</span>
                          <button
                            className={styles.titleEditBtn}
                            title="Rename"
                            onClick={() => startRename(doc)}
                          >
                            ✎
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                  <td className={styles.monoCell}>{formatSize(doc.size_bytes)}</td>
                  <td className={styles.monoCell}>{new Date(doc.created_at).toLocaleDateString()}</td>
                  <td>
                    <span className={`${styles.badge} ${styles[doc.status]}`}>
                      {(doc.status === "processing" || doc.status === "ready") && (
                        <span className={styles.badgeDot} />
                      )}
                      {doc.status[0].toUpperCase() + doc.status.slice(1)}
                    </span>
                  </td>
                  <td>
                    <div className={styles.actionsCell}>
                      {doc.status === "failed" && (
                        <button
                          className={styles.iconActionBtn}
                          disabled={retryingId === doc.id}
                          onClick={() => handleRetry(doc.id)}
                          title={retryingId === doc.id ? "Retrying…" : "Retry ingest"}
                          aria-label="Retry ingest"
                        >
                          <span className={retryingId === doc.id ? styles.spinning : ""}>
                            {ACTION_ICONS.retry}
                          </span>
                        </button>
                      )}
                      {doc.status === "ready" && (
                        <>
                          <button
                            className={styles.iconActionBtn}
                            disabled={extractingId === doc.id}
                            onClick={() => handleExtractActionItems(doc.id)}
                            title={extractingId === doc.id ? "Scanning…" : "Extract action items"}
                            aria-label="Extract action items"
                          >
                            {ACTION_ICONS.extract}
                          </button>
                          <button
                            className={styles.iconActionBtn}
                            onClick={() => openSealPrompt(doc.id)}
                            title="Seal"
                            aria-label="Seal"
                          >
                            {ACTION_ICONS.seal}
                          </button>
                        </>
                      )}
                      {doc.status !== "sealed" && (
                        <button
                          className={styles.iconActionBtn}
                          disabled={viewingId === doc.id}
                          onClick={() => handleView(doc)}
                          title={viewingId === doc.id ? "Opening…" : "Open the file in a new tab"}
                          aria-label="View"
                        >
                          {ACTION_ICONS.view}
                        </button>
                      )}
                      {doc.status === "sealed" && (
                        <button
                          className={styles.iconActionBtn}
                          onClick={() => openUnlockPrompt(doc.id)}
                          title="Unlock"
                          aria-label="Unlock"
                        >
                          {ACTION_ICONS.unlock}
                        </button>
                      )}
                      <button
                        className={`${styles.iconActionBtn} ${styles.iconActionBtnDanger}`}
                        disabled={deletingId === doc.id}
                        onClick={() => requestDelete(doc)}
                        title={deletingId === doc.id ? "Deleting…" : "Delete"}
                        aria-label="Delete"
                      >
                        {ACTION_ICONS.delete}
                      </button>
                    </div>
                  </td>
                </tr>
                {sealPromptFor === doc.id && (
                  <tr>
                    <td colSpan={5} className={styles.actionItemsCell}>
                      <div className={styles.sealPrompt}>
                        <span className={styles.sealPromptLabel}>
                          Choose a passphrase — there is no recovery if you forget it.
                        </span>
                        <input
                          type="password"
                          autoFocus
                          className={styles.sealPromptInput}
                          placeholder="Passphrase"
                          value={sealPassphrase}
                          onChange={(e) => setSealPassphrase(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleConfirmSeal(doc.id);
                            if (e.key === "Escape") setSealPromptFor(null);
                          }}
                          disabled={sealing}
                        />
                        <button
                          className={styles.retryBtn}
                          disabled={!sealPassphrase || sealing}
                          onClick={() => handleConfirmSeal(doc.id)}
                        >
                          {sealing ? "Sealing…" : "Confirm seal"}
                        </button>
                        <button
                          className={styles.retryBtn}
                          disabled={sealing}
                          onClick={() => setSealPromptFor(null)}
                        >
                          Cancel
                        </button>
                        {sealError && <span className={styles.sealPromptError}>{sealError}</span>}
                      </div>
                    </td>
                  </tr>
                )}
                {unlockPromptFor === doc.id && (
                  <tr>
                    <td colSpan={5} className={styles.actionItemsCell}>
                      <div className={styles.sealPrompt}>
                        <span className={styles.sealPromptLabel}>
                          Enter the passphrase this document was sealed with.
                        </span>
                        <input
                          type="password"
                          autoFocus
                          className={styles.sealPromptInput}
                          placeholder="Passphrase"
                          value={unlockPassphrase}
                          onChange={(e) => setUnlockPassphrase(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleConfirmUnlock(doc.id);
                            if (e.key === "Escape") setUnlockPromptFor(null);
                          }}
                          disabled={unlocking}
                        />
                        <button
                          className={styles.retryBtn}
                          disabled={!unlockPassphrase || unlocking}
                          onClick={() => handleConfirmUnlock(doc.id)}
                        >
                          {unlocking ? "Unlocking…" : "Unlock"}
                        </button>
                        <button
                          className={styles.retryBtn}
                          disabled={unlocking}
                          onClick={() => setUnlockPromptFor(null)}
                        >
                          Cancel
                        </button>
                        {unlockError && <span className={styles.sealPromptError}>{unlockError}</span>}
                      </div>
                    </td>
                  </tr>
                )}
                {unsealedContent[doc.id] && (
                  <tr>
                    <td colSpan={5} className={styles.actionItemsCell}>
                      <div className={styles.unsealedHeader}>
                        <span className={styles.sealPromptLabel}>
                          Unlocked — visible only in this view, never saved unsealed.
                        </span>
                        <button className={styles.retryBtn} onClick={() => closeUnsealedContent(doc.id)}>
                          Close
                        </button>
                      </div>
                      {unsealedContent[doc.id].length === 0 ? (
                        <span className={styles.emptyRow}>No content found.</span>
                      ) : (
                        <div className={styles.actionItemsList}>
                          {unsealedContent[doc.id]
                            .slice()
                            .sort((a, b) => a.ordinal - b.ordinal)
                            .map((chunk) => (
                              <div key={chunk.ordinal} className={styles.unsealedChunk}>
                                {chunk.content}
                              </div>
                            ))}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
                {actionItems[doc.id] && (
                  <tr>
                    <td colSpan={5} className={styles.actionItemsCell}>
                      {actionItems[doc.id].length === 0 ? (
                        <span className={styles.emptyRow}>No action items found in this document.</span>
                      ) : (
                        <div className={styles.actionItemsList}>
                          {actionItems[doc.id].map((item) => {
                            const added = addedChunkIds.has(item.source_chunk_id);
                            return (
                              <div key={item.source_chunk_id} className={styles.actionItemRow}>
                                <div>
                                  <div className={styles.actionItemTitle}>{item.title}</div>
                                  {item.description && (
                                    <div className={styles.actionItemDesc}>{item.description}</div>
                                  )}
                                </div>
                                <div className={styles.actionItemActions}>
                                  <button
                                    className={styles.retryBtn}
                                    disabled={added}
                                    onClick={() => handleConfirmActionItem(doc.id, item)}
                                  >
                                    {added ? "Added" : "Add"}
                                  </button>
                                  {!added && (
                                    <button
                                      className={styles.retryBtn}
                                      onClick={() => handleDeclineActionItem(doc.id, item)}
                                    >
                                      Decline
                                    </button>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      {deletePromptFor && (
        <ConfirmModal
          title="Delete document"
          body={
            <>
              Delete <strong>&ldquo;{deletePromptFor.title}&rdquo;</strong>? This can&apos;t be
              undone.
            </>
          }
          confirmLabel={deletingId ? "Deleting…" : "Delete"}
          cancelLabel="Cancel"
          danger
          loading={!!deletingId}
          onConfirm={confirmDelete}
          onCancel={() => setDeletePromptFor(null)}
        />
      )}

      {viewErrorMessage && (
        <ConfirmModal
          title="Can't open this document"
          body={viewErrorMessage}
          confirmLabel="OK"
          onConfirm={() => setViewErrorMessage(null)}
          onCancel={() => setViewErrorMessage(null)}
        />
      )}
    </div>
    </AppShell>
  );
}
