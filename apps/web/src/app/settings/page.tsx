"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import AppShell from "@/components/AppShell";
import { authedFetch } from "@/lib/api";
import type { DocumentRow } from "@/lib/graph/types";
import { createClient } from "@/lib/supabase/client";
import { useAuthedUser } from "@/lib/useAuthedUser";
import styles from "./settings.module.css";

// Stage 4.7 — matches Mockups/ui_kits/settings, with three panes kept
// real and one (API Usage) omitted entirely: it's Stage 4.4's own
// subject matter (token/cost display) under a different name, and
// building any version of it here would be exactly the "layered onto
// the build mid-flight" mistake that stage's own note warns against.
// See phases-and-gates.md's Stage 4.7 entry for the other trims (no
// "Active unlock sessions" — Stage 3.3 never built a way to list/revoke
// claims; "Unseal" links to /documents rather than a new inline flow,
// since Documents doesn't have one either yet).

type Pane = "account" | "security" | "storage";

// CLAUDE.md's documented Supabase free-tier ceiling — static context,
// not a live-queried project-usage number (not exposed by this app's
// own API anywhere).
const INDEXED_QUOTA_BYTES = 500 * 1024 * 1024;
const ORIGINALS_QUOTA_BYTES = 1024 * 1024 * 1024;

// Well above any real image-hosting URL, well below anything that
// could meaningfully bloat the session cookie (see handleProfileSave).
const MAX_AVATAR_URL_LENGTH = 2000;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}b`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}kb`;
  return `${(bytes / (1024 * 1024)).toFixed(2)}mb`;
}

export default function SettingsPage() {
  const { checking, email, displayName, avatarUrl } = useAuthedUser();
  const router = useRouter();
  const [pane, setPane] = useState<Pane>("account");

  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [accountMessage, setAccountMessage] = useState<string | null>(null);
  const [accountError, setAccountError] = useState<string | null>(null);

  const [newDisplayName, setNewDisplayName] = useState("");
  const [newAvatarUrl, setNewAvatarUrl] = useState("");
  const [profileSaving, setProfileSaving] = useState(false);
  const [emailSaving, setEmailSaving] = useState(false);
  const [passwordSaving, setPasswordSaving] = useState(false);

  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [documents, setDocuments] = useState<DocumentRow[]>([]);

  useEffect(() => {
    if (checking) return;
    authedFetch("/api/documents")
      .then((res) => res.json())
      .then((body) => setDocuments(body.documents ?? []));
  }, [checking]);

  useEffect(() => {
    if (email) setNewEmail(email);
  }, [email]);

  useEffect(() => {
    setNewDisplayName(displayName ?? "");
    setNewAvatarUrl(avatarUrl ?? "");
  }, [displayName, avatarUrl]);

  async function handleProfileSave() {
    setAccountMessage(null);
    setAccountError(null);

    const trimmedAvatarUrl = newAvatarUrl.trim();
    // Supabase stores user_metadata inside the session JWT, which rides
    // along as a cookie on every single request (every route, not just
    // this page) — a data: URI or any very long string pasted in here
    // bloats that cookie past the platform's request-header size limit
    // and 494s the entire site for that user, including /signin, with
    // no way back in except clearing cookies by hand. Reject anything
    // that could cause that before it ever reaches Supabase.
    if (trimmedAvatarUrl && !/^https?:\/\//i.test(trimmedAvatarUrl)) {
      setAccountError("Avatar URL must be a real http(s) link, not a pasted image.");
      return;
    }
    if (trimmedAvatarUrl.length > MAX_AVATAR_URL_LENGTH) {
      setAccountError(`Avatar URL is too long (max ${MAX_AVATAR_URL_LENGTH} characters).`);
      return;
    }

    setProfileSaving(true);
    try {
      const supabase = createClient();
      const { error } = await supabase.auth.updateUser({
        data: {
          display_name: newDisplayName.trim() || null,
          avatar_url: trimmedAvatarUrl || null,
        },
      });
      if (error) {
        setAccountError(error.message);
        return;
      }
      setAccountMessage("Profile updated.");
    } finally {
      setProfileSaving(false);
    }
  }

  async function handleEmailSave() {
    setAccountMessage(null);
    setAccountError(null);
    setEmailSaving(true);
    try {
      const supabase = createClient();
      const { error } = await supabase.auth.updateUser({ email: newEmail });
      if (error) {
        setAccountError(error.message);
        return;
      }
      setAccountMessage("Confirmation email sent to the new address.");
    } finally {
      setEmailSaving(false);
    }
  }

  async function handlePasswordUpdate() {
    setAccountMessage(null);
    setAccountError(null);
    if (newPassword.length < 8) {
      setAccountError("Password must be at least 8 characters.");
      return;
    }
    setPasswordSaving(true);
    try {
      const supabase = createClient();
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) {
        setAccountError(error.message);
        return;
      }
      setNewPassword("");
      setAccountMessage("Password updated.");
    } finally {
      setPasswordSaving(false);
    }
  }

  async function handleDeleteAccount() {
    setDeleting(true);
    setDeleteError(null);
    try {
      const res = await authedFetch("/api/account", { method: "DELETE" });
      if (!res.ok) {
        setDeleteError("Couldn't delete your account. Try again.");
        return;
      }
      const supabase = createClient();
      await supabase.auth.signOut();
      router.push("/");
    } catch {
      setDeleteError("Couldn't delete your account. Try again.");
    } finally {
      setDeleting(false);
    }
  }

  if (checking) return null;

  const sealedDocuments = documents.filter((d) => d.status === "sealed");
  const totalIndexedBytes = documents.reduce((sum, d) => sum + (d.size_bytes ?? 0), 0);
  const totalOriginalBytes = documents.reduce((sum, d) => sum + (d.original_size_bytes ?? 0), 0);

  return (
    <AppShell userEmail={email}>
      <div className={styles.shell}>
        <div className={styles.subnav}>
          <div
            className={`${styles.subnavItem} ${pane === "account" ? styles.subnavItemActive : ""}`}
            onClick={() => setPane("account")}
          >
            Account
          </div>
          <div
            className={`${styles.subnavItem} ${pane === "security" ? styles.subnavItemActive : ""}`}
            onClick={() => setPane("security")}
          >
            Security
          </div>
          <div
            className={`${styles.subnavItem} ${pane === "storage" ? styles.subnavItemActive : ""}`}
            onClick={() => setPane("storage")}
          >
            Data &amp; Storage
          </div>
        </div>

        <div className={styles.content}>
          {pane === "account" && (
            <div className={styles.pane}>
              <h1>Account</h1>

              {accountMessage && <p className={styles.statusMessage}>{accountMessage}</p>}
              {accountError && <p className={styles.errorMessage}>{accountError}</p>}

              <div className={styles.card}>
                <h2>Profile</h2>
                {newAvatarUrl && (
                  // eslint-disable-next-line @next/next/no-img-element -- pasted external URL, not a local/optimizable asset.
                  <img src={newAvatarUrl} alt="" className={styles.avatarPreview} />
                )}
                <div className={styles.field}>
                  <label>Display name</label>
                  <input
                    type="text"
                    placeholder={email ?? ""}
                    value={newDisplayName}
                    onChange={(e) => setNewDisplayName(e.target.value)}
                  />
                </div>
                <div className={styles.field}>
                  <label>Avatar URL</label>
                  <input
                    type="url"
                    placeholder="https://…"
                    value={newAvatarUrl}
                    maxLength={MAX_AVATAR_URL_LENGTH}
                    onChange={(e) => setNewAvatarUrl(e.target.value)}
                  />
                </div>
                <button
                  className={`${styles.btn} ${styles.btnGhost}`}
                  disabled={profileSaving}
                  onClick={handleProfileSave}
                >
                  {profileSaving ? "Saving…" : "Save changes"}
                </button>
              </div>

              <div className={styles.card}>
                <h2>Email</h2>
                <div className={styles.field}>
                  <label>Email address</label>
                  <input
                    type="email"
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                  />
                </div>
                <button
                  className={`${styles.btn} ${styles.btnGhost}`}
                  disabled={emailSaving}
                  onClick={handleEmailSave}
                >
                  {emailSaving ? "Saving…" : "Save changes"}
                </button>
              </div>

              <div className={styles.card}>
                <h2>Password</h2>
                <div className={styles.field}>
                  <label>New password</label>
                  <input
                    type="password"
                    placeholder="At least 8 characters"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                  />
                </div>
                <button
                  className={`${styles.btn} ${styles.btnPrimary}`}
                  disabled={passwordSaving}
                  onClick={handlePasswordUpdate}
                >
                  {passwordSaving ? "Updating…" : "Update password"}
                </button>
              </div>

              <div className={`${styles.card} ${styles.dangerZone}`}>
                <h2>Delete account</h2>
                <p className={styles.desc}>
                  Permanently deletes every document, chat, kanban board, and
                  task in your vault, including sealed documents. This
                  cannot be undone. Your account will remain able to sign
                  in, empty.
                </p>
                <div className={styles.confirmRow}>
                  <div className={styles.field}>
                    <label>Type DELETE to confirm</label>
                    <input
                      type="text"
                      value={deleteConfirmText}
                      onChange={(e) => setDeleteConfirmText(e.target.value)}
                    />
                  </div>
                  <button
                    className={`${styles.btn} ${styles.btnDanger}`}
                    disabled={deleteConfirmText !== "DELETE" || deleting}
                    onClick={handleDeleteAccount}
                  >
                    {deleting ? "Deleting…" : "Delete account"}
                  </button>
                </div>
                {deleteError && <p className={styles.errorMessage}>{deleteError}</p>}
              </div>
            </div>
          )}

          {pane === "security" && (
            <div className={styles.pane}>
              <h1>Security</h1>
              <div className={styles.card}>
                <h2>Sealed documents</h2>
                <p className={styles.desc}>
                  Files sealed behind a passphrase. Unlock them from Documents.
                </p>
                <div className={styles.rowList}>
                  {sealedDocuments.length === 0 && (
                    <p className={styles.desc} style={{ margin: 0 }}>
                      No sealed documents.
                    </p>
                  )}
                  {sealedDocuments.map((doc) => (
                    <div key={doc.id} className={styles.docRow}>
                      <span className={styles.lockBadge}>Sealed</span>
                      <span className={styles.docName}>{doc.title}</span>
                      <button
                        className={`${styles.btn} ${styles.btnGhost}`}
                        onClick={() => router.push("/documents")}
                      >
                        Unseal
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {pane === "storage" && (
            <div className={styles.pane}>
              <h1>Data &amp; Storage</h1>
              <div className={styles.card}>
                <h2>Usage</h2>
                <div className={styles.storageBlock}>
                  <div className={styles.storageLabelRow}>
                    <span>Indexed content</span>
                    <span className={styles.storageValue}>
                      {formatBytes(totalIndexedBytes)} / {formatBytes(INDEXED_QUOTA_BYTES)}
                    </span>
                  </div>
                  <div className={styles.storageTrack}>
                    <div
                      className={styles.storageFill}
                      style={{
                        width: `${Math.min(100, (totalIndexedBytes / INDEXED_QUOTA_BYTES) * 100)}%`,
                        background: "linear-gradient(90deg, var(--accent-primary-active), var(--accent-primary-hover))",
                      }}
                    />
                  </div>
                </div>
                <div className={styles.storageBlock}>
                  <div className={styles.storageLabelRow}>
                    <span>Original files</span>
                    <span className={styles.storageValue}>
                      {formatBytes(totalOriginalBytes)} / {formatBytes(ORIGINALS_QUOTA_BYTES)}
                    </span>
                  </div>
                  <div className={styles.storageTrack}>
                    <div
                      className={styles.storageFill}
                      style={{
                        width: `${Math.min(100, (totalOriginalBytes / ORIGINALS_QUOTA_BYTES) * 100)}%`,
                        background: "linear-gradient(90deg, var(--accent-secondary-active), var(--accent-secondary-hover))",
                      }}
                    />
                  </div>
                </div>
              </div>

              <div className={styles.card}>
                <h2>Storage by document</h2>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th>Original</th>
                      <th>Indexed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((doc) => (
                      <tr key={doc.id}>
                        <td>{doc.title}</td>
                        <td className={styles.monoCell}>
                          {doc.original_size_bytes != null
                            ? formatBytes(doc.original_size_bytes)
                            : "—"}
                        </td>
                        <td className={styles.monoCell}>
                          {doc.status === "sealed" ? "—" : formatBytes(doc.size_bytes)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
