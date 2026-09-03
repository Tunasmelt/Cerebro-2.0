"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import AppShell from "@/components/AppShell";
import { authedFetch } from "@/lib/api";
import { sealBytes } from "@/lib/crypto/seal";
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

// Mirrors services/api/app/core/documents_storage.py's ALLOWED_MIME_TYPES —
// fast client-side feedback only, Supabase Storage's bucket policy is the
// real enforcement boundary (see that module's docstring).
const ALLOWED_MIME_TYPES: Record<string, string> = {
  "text/plain": "TXT",
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

  const fetchDocuments = useCallback(async () => {
    const res = await authedFetch("/api/documents");
    if (!res.ok) return;
    const body = await res.json();
    setDocuments(body.documents ?? []);
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

      // Each chunk is sealed independently with its own fresh salt/nonce
      // (sealBytes generates both per call) — the passphrase itself
      // never leaves this function, only the resulting ciphertext does.
      const sealedChunks = await Promise.all(
        chunks.map(async (chunk) => {
          const payload = await sealBytes(new TextEncoder().encode(chunk.content), passphrase);
          return {
            ordinal: chunk.ordinal,
            content_ciphertext: bytesToBase64(payload.ciphertext),
            salt: bytesToBase64(payload.salt),
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
          <span className={styles.hint}>PDF, images, plain text — up to 50MB</span>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={Object.keys(ALLOWED_MIME_TYPES).join(",")}
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
            {documents.length === 0 && (
              <tr>
                <td colSpan={5} className={styles.emptyRow}>
                  No documents yet — drag one in above.
                </td>
              </tr>
            )}
            {documents.map((doc, i) => (
              <Fragment key={doc.id}>
                <tr style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}>
                  <td>
                    <div className={styles.titleCell}>
                      <div className={styles.typeIcon}>{typeLabel(doc.mime)}</div>
                      {doc.title}
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
                    {doc.status === "failed" && (
                      <button
                        className={styles.retryBtn}
                        disabled={retryingId === doc.id}
                        onClick={() => handleRetry(doc.id)}
                      >
                        {retryingId === doc.id ? "Retrying…" : "Retry"}
                      </button>
                    )}
                    {doc.status === "ready" && (
                      <>
                        <button
                          className={styles.retryBtn}
                          disabled={extractingId === doc.id}
                          onClick={() => handleExtractActionItems(doc.id)}
                        >
                          {extractingId === doc.id ? "Scanning…" : "Extract action items"}
                        </button>{" "}
                        <button className={styles.retryBtn} onClick={() => openSealPrompt(doc.id)}>
                          Seal
                        </button>
                      </>
                    )}
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
    </div>
    </AppShell>
  );
}
