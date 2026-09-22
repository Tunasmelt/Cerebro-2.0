import { useState } from "react";

function Toast({ message, onDone }: { message: string; onDone: () => void }) {
  setTimeout(onDone, 2200);
  return (
    <div
      className="fixed bottom-6 right-6 px-4 py-3 rounded-xl text-sm font-medium z-50"
      style={{
        background: "#141b2d",
        border: "1px solid rgba(16,185,129,0.3)",
        color: "#10b981",
        boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
        animation: "fade-up 0.25s ease forwards",
      }}
    >
      {message}
    </div>
  );
}

export default function Settings() {
  const [displayName, setDisplayName] = useState("Tony");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [activeSection, setActiveSection] = useState<"profile" | "security" | "data">("profile");
  const [toast, setToast] = useState<string | null>(null);

  const showToast = (msg: string) => { setToast(null); setTimeout(() => setToast(msg), 10); };

  const avatarInitial = displayName.trim().charAt(0).toUpperCase() || "?";

  return (
    <div className="flex h-full" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      {/* Sub-nav */}
      <div className="w-44 shrink-0 p-3" style={{ borderRight: "1px solid rgba(255,255,255,0.05)" }}>
        {(["profile", "security", "data"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setActiveSection(s)}
            className="w-full text-left text-sm px-3 py-1.5 rounded-lg mb-0.5 font-medium transition-colors"
            style={{
              color: activeSection === s ? "#e8ecf5" : "#6b7a99",
              background: activeSection === s ? "rgba(124,90,246,0.1)" : "transparent",
            }}
            onMouseEnter={(e) => { if (activeSection !== s) e.currentTarget.style.background = "rgba(255,255,255,0.03)"; }}
            onMouseLeave={(e) => { if (activeSection !== s) e.currentTarget.style.background = "transparent"; }}
          >
            {s === "data" ? "Data & Storage" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeSection === "profile" && (
          <div className="max-w-lg space-y-5">
            <div className="rounded-xl p-5" style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)" }}>
              <h2 className="text-base font-semibold mb-4" style={{ color: "#f0f2f7", fontFamily: "'Outfit', sans-serif" }}>
                Profile
              </h2>

              {/* Avatar preview */}
              <div className="flex items-center gap-4 mb-5">
                {avatarUrl ? (
                  <img
                    src={avatarUrl}
                    alt={displayName}
                    className="w-14 h-14 rounded-full object-cover shrink-0"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                ) : (
                  <div
                    className="w-14 h-14 rounded-full flex items-center justify-center text-xl font-bold shrink-0"
                    style={{ background: "linear-gradient(135deg, #7c5af6, #22d3ee)", color: "#fff" }}
                  >
                    {avatarInitial}
                  </div>
                )}
                <div>
                  <div className="text-sm font-medium" style={{ color: "#e8ecf5" }}>{displayName || "—"}</div>
                  <div className="text-xs mt-0.5" style={{ color: "#3d4a63" }}>tonyudonta12@gmail.com</div>
                </div>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium mb-1.5" style={{ color: "#6b7a99" }}>Display name</label>
                  <input
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-all"
                    style={{ background: "#141b2d", border: "1px solid rgba(255,255,255,0.08)", color: "#e8ecf5" }}
                    onFocus={(e) => { e.target.style.borderColor = "rgba(124,90,246,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(124,90,246,0.1)"; }}
                    onBlur={(e) => { e.target.style.borderColor = "rgba(255,255,255,0.08)"; e.target.style.boxShadow = "none"; }}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1.5" style={{ color: "#6b7a99" }}>Avatar URL</label>
                  <input
                    value={avatarUrl}
                    onChange={(e) => setAvatarUrl(e.target.value)}
                    placeholder="https://…"
                    className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-all"
                    style={{ background: "#141b2d", border: "1px solid rgba(255,255,255,0.08)", color: "#e8ecf5", fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}
                    onFocus={(e) => { e.target.style.borderColor = "rgba(124,90,246,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(124,90,246,0.1)"; }}
                    onBlur={(e) => { e.target.style.borderColor = "rgba(255,255,255,0.08)"; e.target.style.boxShadow = "none"; }}
                  />
                </div>
              </div>

              <button
                onClick={() => showToast("Profile saved")}
                className="mt-4 px-4 py-2 rounded-lg text-sm font-medium transition-all"
                style={{ background: "rgba(255,255,255,0.06)", color: "#9aa5bc", border: "1px solid rgba(255,255,255,0.08)" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.1)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
              >
                Save changes
              </button>
            </div>

            {/* Email card */}
            <div className="rounded-xl p-5" style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)" }}>
              <h2 className="text-base font-semibold mb-4" style={{ color: "#f0f2f7", fontFamily: "'Outfit', sans-serif" }}>
                Email
              </h2>
              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: "#6b7a99" }}>Email address</label>
                <input
                  value="tonyudonta12@gmail.com"
                  readOnly
                  className="w-full px-3 py-2.5 rounded-lg text-sm outline-none"
                  style={{ background: "#141b2d", border: "1px solid rgba(255,255,255,0.06)", color: "#6b7a99", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}
                />
              </div>
              <button
                onClick={() => showToast("Email update link sent")}
                className="mt-4 px-4 py-2 rounded-lg text-sm font-medium transition-all"
                style={{ background: "rgba(255,255,255,0.06)", color: "#9aa5bc", border: "1px solid rgba(255,255,255,0.08)" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.1)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
              >
                Send change link
              </button>
            </div>
          </div>
        )}

        {activeSection === "security" && (
          <div className="max-w-lg space-y-5">
            <div className="rounded-xl p-5" style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)" }}>
              <h2 className="text-base font-semibold mb-4" style={{ color: "#f0f2f7", fontFamily: "'Outfit', sans-serif" }}>
                Password
              </h2>
              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: "#6b7a99" }}>New password</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="At least 8 characters"
                  className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-all"
                  style={{ background: "#141b2d", border: "1px solid rgba(255,255,255,0.08)", color: "#e8ecf5" }}
                  onFocus={(e) => { e.target.style.borderColor = "rgba(124,90,246,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(124,90,246,0.1)"; }}
                  onBlur={(e) => { e.target.style.borderColor = "rgba(255,255,255,0.08)"; e.target.style.boxShadow = "none"; }}
                />
                {newPassword.length > 0 && newPassword.length < 8 && (
                  <p className="mt-1.5 text-xs" style={{ color: "#f59e0b" }}>Must be at least 8 characters</p>
                )}
              </div>
              <button
                onClick={() => { if (newPassword.length >= 8) { setNewPassword(""); showToast("Password updated"); } }}
                disabled={newPassword.length < 8}
                className="mt-4 px-4 py-2 rounded-lg text-sm font-semibold transition-all"
                style={{
                  background: newPassword.length >= 8 ? "#7c5af6" : "rgba(124,90,246,0.3)",
                  color: "#fff",
                  cursor: newPassword.length >= 8 ? "pointer" : "not-allowed",
                }}
              >
                Update password
              </button>
            </div>

            {/* Delete */}
            <div className="rounded-xl p-5" style={{ background: "#0e1320", border: "1px solid rgba(244,63,94,0.2)" }}>
              <h2 className="text-base font-semibold mb-2" style={{ color: "#f43f5e", fontFamily: "'Outfit', sans-serif" }}>
                Delete account
              </h2>
              <p className="text-xs leading-relaxed mb-4" style={{ color: "#6b7a99", lineHeight: 1.7 }}>
                Permanently deletes every document, chat, kanban board, and task in your vault, including sealed
                documents. This cannot be undone. Your account will remain able to sign in, empty.
              </p>
              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: "#6b7a99" }}>
                  Type DELETE to confirm
                </label>
                <input
                  value={deleteConfirm}
                  onChange={(e) => setDeleteConfirm(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-all font-mono"
                  style={{
                    background: "#141b2d",
                    border: "1px solid rgba(244,63,94,0.2)",
                    color: "#f43f5e",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                  placeholder="DELETE"
                />
              </div>
              <button
                onClick={() => { if (deleteConfirm === "DELETE") showToast("Account scheduled for deletion"); }}
                disabled={deleteConfirm !== "DELETE"}
                className="mt-3 px-4 py-2 rounded-lg text-sm font-semibold transition-all"
                style={{
                  background: deleteConfirm === "DELETE" ? "#f43f5e" : "transparent",
                  color: deleteConfirm === "DELETE" ? "#fff" : "#f43f5e",
                  border: "1px solid rgba(244,63,94,0.4)",
                  cursor: deleteConfirm === "DELETE" ? "pointer" : "default",
                  opacity: deleteConfirm === "DELETE" ? 1 : 0.5,
                }}
              >
                Delete account
              </button>
            </div>
          </div>
        )}

        {activeSection === "data" && (
          <div className="max-w-lg">
            <div className="rounded-xl p-5" style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)" }}>
              <h2 className="text-base font-semibold mb-4" style={{ color: "#f0f2f7", fontFamily: "'Outfit', sans-serif" }}>
                Data & Storage
              </h2>
              <div className="space-y-4">
                {[
                  { label: "Documents", value: "12 files", sub: "6.8 MB total" },
                  { label: "Embeddings", value: "4,821 vectors", sub: "Graph index" },
                  { label: "Chats", value: "7 sessions", sub: "Sep 3 – Sep 13" },
                  { label: "Tasks & Cards", value: "11 items", sub: "Across 3 columns" },
                ].map((row) => (
                  <div key={row.label} className="flex items-center justify-between py-3"
                    style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                    <div>
                      <div className="text-sm font-medium" style={{ color: "#e8ecf5" }}>{row.label}</div>
                      <div className="text-xs mt-0.5" style={{ color: "#3d4a63" }}>{row.sub}</div>
                    </div>
                    <div className="text-sm font-mono" style={{ color: "#22d3ee", fontFamily: "'JetBrains Mono', monospace" }}>
                      {row.value}
                    </div>
                  </div>
                ))}
              </div>
              <button
                onClick={() => showToast("Export started — check your email")}
                className="mt-4 px-4 py-2 rounded-lg text-sm font-medium transition-all"
                style={{ background: "rgba(255,255,255,0.06)", color: "#9aa5bc", border: "1px solid rgba(255,255,255,0.08)" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.1)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
              >
                Export all data
              </button>
            </div>
          </div>
        )}
      </div>

      {toast && <Toast key={toast + Date.now()} message={toast} onDone={() => setToast(null)} />}
    </div>
  );
}
