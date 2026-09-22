import { useState, type ReactNode } from "react";
import Brain from "./Brain";
import Documents from "./Documents";
import Chat from "./Chat";
import Kanban from "./Kanban";
import Tasks from "./Tasks";
import Playground from "./Playground";
import Settings from "./Settings";

export type View = "brain" | "documents" | "chat" | "kanban" | "tasks" | "playground" | "settings";

const navItems: { id: View; label: string; icon: (active: boolean) => ReactNode }[] = [
  {
    id: "brain",
    label: "Brain",
    icon: (active) => (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <circle cx="4" cy="7.5" r="2" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} />
        <circle cx="11" cy="4" r="1.5" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} />
        <circle cx="11" cy="11" r="1.5" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} />
        <line x1="6" y1="7.5" x2="9.5" y2="4.5" stroke="currentColor" strokeWidth="1" />
        <line x1="6" y1="7.5" x2="9.5" y2="10.5" stroke="currentColor" strokeWidth="1" />
      </svg>
    ),
  },
  {
    id: "documents",
    label: "Documents",
    icon: (active) => (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <rect x="2.5" y="1.5" width="10" height="12" rx="1.5" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} />
        <line x1="5" y1="5" x2="10" y2="5" stroke="currentColor" strokeWidth="1" />
        <line x1="5" y1="7.5" x2="10" y2="7.5" stroke="currentColor" strokeWidth="1" />
        <line x1="5" y1="10" x2="8" y2="10" stroke="currentColor" strokeWidth="1" />
      </svg>
    ),
  },
  {
    id: "chat",
    label: "Chat",
    icon: (active) => (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <path d="M2 2.5h11a.5.5 0 01.5.5v7a.5.5 0 01-.5.5H5L2 13V3a.5.5 0 01.5-.5z" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: "kanban",
    label: "Kanban",
    icon: (active) => (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <rect x="1.5" y="2.5" width="3.5" height="10" rx="1" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} />
        <rect x="5.75" y="2.5" width="3.5" height="7" rx="1" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} />
        <rect x="10" y="2.5" width="3.5" height="5" rx="1" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} />
      </svg>
    ),
  },
  {
    id: "tasks",
    label: "Tasks",
    icon: (active) => (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <rect x="1.5" y="1.5" width="12" height="12" rx="2" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} />
        <path d="M4.5 7.5l2 2 4-4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: "playground",
    label: "Playground",
    icon: (active) => (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <polygon points="3,2 12,7.5 3,13" stroke="currentColor" strokeWidth={active ? "1.5" : "1.2"} strokeLinejoin="round" />
      </svg>
    ),
  },
];

export default function AppShell() {
  const [view, setView] = useState<View>("brain");
  const [collapsed, setCollapsed] = useState(false);

  const renderView = () => {
    switch (view) {
      case "brain": return <Brain onNavigate={(v) => setView(v)} />;
      case "documents": return <Documents />;
      case "chat": return <Chat />;
      case "kanban": return <Kanban />;
      case "tasks": return <Tasks />;
      case "playground": return <Playground />;
      case "settings": return <Settings />;
    }
  };

  return (
    <div className="flex h-screen" style={{ background: "#080b12", fontFamily: "'DM Sans', sans-serif" }}>
      {/* Sidebar */}
      <aside
        className="flex flex-col shrink-0 transition-all duration-200"
        style={{
          width: collapsed ? 52 : 180,
          background: "#0a0e1a",
          borderRight: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        {/* Logo */}
        <div className="flex items-center justify-between px-3 h-12" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
          {!collapsed && (
            <div className="flex items-center gap-2">
              <svg width="18" height="18" viewBox="0 0 22 22" fill="none">
                <circle cx="6" cy="11" r="3" fill="#7c5af6" />
                <circle cx="16" cy="6" r="2.5" fill="#22d3ee" />
                <circle cx="16" cy="16" r="2" fill="#7c5af6" opacity="0.7" />
                <line x1="9" y1="11" x2="13.5" y2="7" stroke="rgba(255,255,255,0.3)" strokeWidth="1" />
                <line x1="9" y1="11" x2="13.5" y2="15" stroke="rgba(255,255,255,0.3)" strokeWidth="1" />
              </svg>
              <span style={{ fontFamily: "'Outfit', sans-serif", fontWeight: 700, fontSize: 14, color: "#e8ecf5" }}>
                Cerebro
              </span>
            </div>
          )}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-1.5 rounded-md transition-colors"
            style={{
              color: "#3d4a63",
              marginLeft: collapsed ? "auto" : 0,
              marginRight: collapsed ? "auto" : 0,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "#9aa5bc")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "#3d4a63")}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              {collapsed
                ? <path d="M5 2l5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                : <path d="M9 2L4 7l5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              }
            </svg>
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-3 overflow-y-auto px-2">
          {navItems.map((item) => {
            const active = view === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setView(item.id)}
                className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-sm mb-0.5 text-left transition-all"
                style={{
                  color: active ? "#e8ecf5" : "#6b7a99",
                  background: active ? "rgba(124,90,246,0.12)" : "transparent",
                  fontWeight: active ? 500 : 400,
                }}
                onMouseEnter={(e) => {
                  if (!active) e.currentTarget.style.background = "rgba(255,255,255,0.04)";
                  if (!active) e.currentTarget.style.color = "#c4cdd8";
                }}
                onMouseLeave={(e) => {
                  if (!active) e.currentTarget.style.background = "transparent";
                  if (!active) e.currentTarget.style.color = "#6b7a99";
                }}
                title={collapsed ? item.label : undefined}
              >
                <span className="shrink-0" style={{ color: active ? "#7c5af6" : "inherit" }}>
                  {item.icon(active)}
                </span>
                {!collapsed && <span>{item.label}</span>}
              </button>
            );
          })}
        </nav>

        {/* Bottom */}
        <div className="px-2 py-3" style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
          <button
            onClick={() => setView("settings")}
            className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-sm transition-all"
            style={{
              color: view === "settings" ? "#e8ecf5" : "#6b7a99",
              background: view === "settings" ? "rgba(124,90,246,0.12)" : "transparent",
            }}
            onMouseEnter={(e) => {
              if (view !== "settings") { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; e.currentTarget.style.color = "#c4cdd8"; }
            }}
            onMouseLeave={(e) => {
              if (view !== "settings") { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "#6b7a99"; }
            }}
          >
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none" className="shrink-0"
              style={{ color: view === "settings" ? "#7c5af6" : "inherit" }}>
              <circle cx="7.5" cy="7.5" r="2" stroke="currentColor" strokeWidth="1.2" />
              <path d="M7.5 1.5v1.2M7.5 12.3v1.2M1.5 7.5h1.2M12.3 7.5h1.2M3.2 3.2l.85.85M10.95 10.95l.85.85M3.2 11.8l.85-.85M10.95 4.05l.85-.85"
                stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
            {!collapsed && <span>Settings</span>}
          </button>

          {!collapsed && (
            <button
              onClick={() => setView("settings")}
              className="flex items-center gap-2.5 px-2 py-1.5 mt-1 w-full rounded-md transition-colors"
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.03)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <div
                className="w-6 h-6 rounded-full shrink-0 flex items-center justify-center text-xs font-bold"
                style={{ background: "linear-gradient(135deg, #7c5af6, #22d3ee)", color: "#fff" }}
              >
                T
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium truncate text-left" style={{ color: "#9aa5bc" }}>Tony</div>
              </div>
            </button>
          )}
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <div
          className="flex items-center justify-end px-5 h-12 shrink-0"
          style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}
        >
          <div className="flex items-center gap-2">
            <button
              className="w-7 h-7 rounded-md flex items-center justify-center transition-colors"
              style={{ color: "#6b7a99", background: "rgba(255,255,255,0.04)" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.08)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.04)")}
              title="New item"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <line x1="7" y1="1" x2="7" y2="13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <line x1="1" y1="7" x2="13" y2="7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold cursor-pointer transition-opacity"
              style={{ background: "linear-gradient(135deg, #7c5af6, #22d3ee)", color: "#fff" }}
              onClick={() => setView("settings")}
              onMouseEnter={(e) => ((e.target as HTMLElement).style.opacity = "0.8")}
              onMouseLeave={(e) => ((e.target as HTMLElement).style.opacity = "1")}
            >
              T
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-auto">
          {renderView()}
        </div>
      </main>
    </div>
  );
}
