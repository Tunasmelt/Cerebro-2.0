import { useState, useRef } from "react";

interface Doc {
  id: number;
  name: string;
  type: "PDF" | "JPG" | "PNG" | "MD" | "TXT";
  size: string;
  uploaded: string;
  status: "Ready" | "Processing";
}

const DOCS: Doc[] = [
  { id: 1, name: "677228862764322103.jpg", type: "JPG", size: "28.2 kb", uploaded: "9/7/2026", status: "Ready" },
  { id: 2, name: "Full Stack AI Developer.pdf", type: "PDF", size: "386.0 kb", uploaded: "9/7/2026", status: "Ready" },
  { id: 3, name: "Screenshot 2026-08-23 232208.png", type: "PNG", size: "1.1 mb", uploaded: "9/7/2026", status: "Ready" },
  { id: 4, name: "870883846715248160.jpg", type: "JPG", size: "30.2 kb", uploaded: "9/7/2026", status: "Ready" },
  { id: 5, name: "326229566779091388.jpg", type: "JPG", size: "53.7 kb", uploaded: "9/7/2026", status: "Ready" },
  { id: 6, name: "742038476149699835.jpg", type: "JPG", size: "28.6 kb", uploaded: "9/7/2026", status: "Ready" },
  { id: 7, name: "BrightPro Paper", type: "PDF", size: "4.7 mb", uploaded: "9/7/2026", status: "Ready" },
  { id: 8, name: "IR Misses the Mark", type: "PDF", size: "587.7 kb", uploaded: "9/7/2026", status: "Ready" },
  { id: 9, name: "ForkedRap-Layer1-Architecture", type: "MD", size: "27.8 kb", uploaded: "9/5/2026", status: "Ready" },
  { id: 10, name: "Retention Marketing Campaigns", type: "PDF", size: "127.0 kb", uploaded: "9/4/2026", status: "Ready" },
  { id: 11, name: "Junior IT Specialist", type: "PDF", size: "307.1 kb", uploaded: "9/4/2026", status: "Ready" },
  { id: 12, name: "Yaras Schedule", type: "JPG", size: "101.9 kb", uploaded: "9/3/2026", status: "Ready" },
];

const TYPE_COLORS: Record<string, string> = {
  PDF: "#f43f5e",
  JPG: "#22d3ee",
  PNG: "#10b981",
  MD: "#f59e0b",
  TXT: "#6b7a99",
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} b`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kb`;
  return `${(bytes / 1024 / 1024).toFixed(1)} mb`;
}

function getExtType(name: string): Doc["type"] {
  const ext = name.split(".").pop()?.toUpperCase() ?? "TXT";
  if (["JPG", "JPEG"].includes(ext)) return "JPG";
  if (ext === "PNG") return "PNG";
  if (ext === "PDF") return "PDF";
  if (ext === "MD") return "MD";
  return "TXT";
}

function TypeBadge({ type }: { type: string }) {
  return (
    <span
      className="inline-flex items-center justify-center rounded px-1.5 font-mono font-semibold shrink-0"
      style={{
        background: `${TYPE_COLORS[type] || "#6b7a99"}18`,
        color: TYPE_COLORS[type] || "#6b7a99",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 10,
        height: 18,
        minWidth: 30,
      }}
    >
      {type}
    </span>
  );
}

let nextDocId = 200;

export default function Documents() {
  const [dragging, setDragging] = useState(false);
  const [docs, setDocs] = useState(DOCS);
  const [search, setSearch] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    const today = new Date();
    const dateStr = `${today.getMonth() + 1}/${today.getDate()}/${today.getFullYear()}`;
    const newDocs: Doc[] = Array.from(files).map((f) => ({
      id: nextDocId++,
      name: f.name,
      type: getExtType(f.name),
      size: formatBytes(f.size),
      uploaded: dateStr,
      status: "Processing" as const,
    }));
    setDocs((prev) => [...newDocs, ...prev]);
    // Simulate processing completing
    setTimeout(() => {
      setDocs((prev) =>
        prev.map((d) =>
          newDocs.find((n) => n.id === d.id) ? { ...d, status: "Ready" } : d
        )
      );
    }, 2000);
  };

  const filtered = docs.filter((d) =>
    !search || d.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-6 max-w-5xl" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <div className="flex items-center justify-between mb-6">
        <h1
          className="text-2xl font-bold"
          style={{ fontFamily: "'Outfit', sans-serif", color: "#f0f2f7", letterSpacing: "-0.01em" }}
        >
          Documents
        </h1>
        {/* Search */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
          style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)", width: 220 }}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ color: "#3d4a63", flexShrink: 0 }}>
            <circle cx="5" cy="5" r="3.5" stroke="currentColor" strokeWidth="1.3" />
            <line x1="7.8" y1="7.8" x2="11" y2="11" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter documents…"
            className="flex-1 bg-transparent text-sm outline-none"
            style={{ color: "#e8ecf5" }}
          />
          {search && (
            <button onClick={() => setSearch("")} style={{ color: "#3d4a63" }}>
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => addFiles(e.target.files)}
        accept=".pdf,.jpg,.jpeg,.png,.md,.txt"
      />

      {/* Drop zone */}
      <div
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
        className="rounded-xl mb-5 flex flex-col items-center justify-center py-8 transition-all cursor-pointer"
        style={{
          border: `1.5px dashed ${dragging ? "#7c5af6" : "rgba(255,255,255,0.1)"}`,
          background: dragging ? "rgba(124,90,246,0.04)" : "transparent",
        }}
        onMouseEnter={(e) => { if (!dragging) e.currentTarget.style.borderColor = "rgba(255,255,255,0.18)"; }}
        onMouseLeave={(e) => { if (!dragging) e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)"; }}
      >
        <div className="w-8 h-8 rounded-lg mb-3 flex items-center justify-center" style={{ background: "rgba(255,255,255,0.04)" }}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M8 2v8M5 5l3-3 3 3" stroke="#6b7a99" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M2 11v1.5A1.5 1.5 0 003.5 14h9a1.5 1.5 0 001.5-1.5V11" stroke="#6b7a99" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
        <p className="text-sm font-medium" style={{ color: "#9aa5bc" }}>
          Drag files here, or <span style={{ color: "#7c5af6" }}>click to browse</span>
        </p>
        <p className="text-xs mt-1" style={{ color: "#3d4a63" }}>
          PDF, images, plain text, markdown — up to 50MB
        </p>
      </div>

      {/* Table */}
      <div className="rounded-xl overflow-hidden" style={{ border: "1px solid rgba(255,255,255,0.07)", background: "#0e1320" }}>
        <div
          className="grid text-xs font-semibold tracking-wide uppercase px-4 py-2.5"
          style={{
            gridTemplateColumns: "1fr 80px 100px 100px 80px",
            color: "#3d4a63",
            borderBottom: "1px solid rgba(255,255,255,0.05)",
            letterSpacing: "0.06em",
          }}
        >
          <span>Title</span>
          <span className="text-right">Size</span>
          <span className="text-right">Uploaded</span>
          <span className="text-right">Status</span>
          <span />
        </div>

        {filtered.length === 0 && (
          <div className="px-4 py-8 text-center text-sm" style={{ color: "#3d4a63" }}>
            No documents match "{search}"
          </div>
        )}

        {filtered.map((doc, i) => (
          <div
            key={doc.id}
            className="grid items-center px-4 py-2.5 transition-colors cursor-pointer group"
            style={{
              gridTemplateColumns: "1fr 80px 100px 100px 80px",
              borderBottom: i < filtered.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.02)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <TypeBadge type={doc.type} />
              <span className="text-sm truncate" style={{ color: "#c4cdd8" }}>
                {doc.name}
              </span>
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: "#3d4a63" }}>
                <path d="M2 8L8 2M8 2H4M8 2v4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
            </div>
            <div className="text-right text-xs font-mono" style={{ color: "#6b7a99", fontFamily: "'JetBrains Mono', monospace" }}>
              {doc.size}
            </div>
            <div className="text-right text-xs font-mono" style={{ color: "#6b7a99", fontFamily: "'JetBrains Mono', monospace" }}>
              {doc.uploaded}
            </div>
            <div className="text-right">
              {doc.status === "Processing" ? (
                <span className="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full"
                  style={{ color: "#f59e0b", background: "rgba(245,158,11,0.1)" }}>
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#f59e0b", animation: "pulse 1s ease-in-out infinite" }} />
                  Processing
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full"
                  style={{ color: "#10b981", background: "rgba(16,185,129,0.1)" }}>
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#10b981" }} />
                  Ready
                </span>
              )}
            </div>
            <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button className="p-1 rounded transition-colors" style={{ color: "#6b7a99" }} title="Details"
                onMouseEnter={(e) => (e.currentTarget.style.color = "#9aa5bc")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "#6b7a99")}
              >
                <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                  <rect x="1" y="1" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.2" />
                  <line x1="4" y1="6.5" x2="9" y2="6.5" stroke="currentColor" strokeWidth="1" />
                  <line x1="4" y1="4.5" x2="9" y2="4.5" stroke="currentColor" strokeWidth="1" />
                  <line x1="4" y1="8.5" x2="7" y2="8.5" stroke="currentColor" strokeWidth="1" />
                </svg>
              </button>
              <button className="p-1 rounded transition-colors" style={{ color: "#6b7a99" }} title="Lock"
                onMouseEnter={(e) => (e.currentTarget.style.color = "#f59e0b")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "#6b7a99")}
              >
                <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                  <rect x="3" y="5.5" width="7" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
                  <path d="M4.5 5.5V4a2 2 0 014 0v1.5" stroke="currentColor" strokeWidth="1.2" />
                </svg>
              </button>
              <button className="p-1 rounded transition-colors" style={{ color: "#6b7a99" }} title="View"
                onMouseEnter={(e) => (e.currentTarget.style.color = "#22d3ee")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "#6b7a99")}
              >
                <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                  <ellipse cx="6.5" cy="6.5" rx="5" ry="3.5" stroke="currentColor" strokeWidth="1.2" />
                  <circle cx="6.5" cy="6.5" r="1.5" stroke="currentColor" strokeWidth="1.2" />
                </svg>
              </button>
              <button
                className="p-1 rounded transition-colors"
                style={{ color: "#6b7a99" }}
                title="Delete"
                onClick={() => setDocs((d) => d.filter((x) => x.id !== doc.id))}
                onMouseEnter={(e) => (e.currentTarget.style.color = "#f43f5e")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "#6b7a99")}
              >
                <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                  <path d="M2 3.5h9M5 3.5V2.5a.5.5 0 01.5-.5h2a.5.5 0 01.5.5v1M10 3.5l-.6 7a1 1 0 01-1 .9H4.6a1 1 0 01-1-.9L3 3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                </svg>
              </button>
            </div>
          </div>
        ))}
      </div>

      {docs.length > 0 && (
        <div className="mt-3 text-xs" style={{ color: "#3d4a63", fontFamily: "'JetBrains Mono', monospace" }}>
          {filtered.length} of {docs.length} documents
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.5; } 50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
