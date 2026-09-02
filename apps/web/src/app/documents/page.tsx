"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import AppShell from "@/components/AppShell";
import { authedFetch } from "@/lib/api";
import type { DocumentRow } from "@/lib/graph/types";
import { createClient } from "@/lib/supabase/client";
import { useAuthedUser } from "@/lib/useAuthedUser";
import styles from "./documents.module.css";

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
              <tr key={doc.id} style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}>
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </div>
    </AppShell>
  );
}
