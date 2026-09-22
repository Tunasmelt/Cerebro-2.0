import { useState } from "react";

type Priority = "high" | "medium" | "low";

interface Task {
  id: number;
  text: string;
  done: boolean;
  priority: Priority;
}

const INIT_TASKS: Task[] = [
  { id: 1, text: "Review BrightPro Paper conclusions", done: false, priority: "high" },
  { id: 2, text: "Set up retrieval pipeline for new docs", done: false, priority: "high" },
  { id: 3, text: "Annotate ForkedRap architecture nodes", done: true, priority: "medium" },
  { id: 4, text: "Export September chat history", done: false, priority: "low" },
  { id: 5, text: "Update retention marketing doc tags", done: true, priority: "low" },
];

const PRIORITY_COLORS: Record<Priority, string> = {
  high: "#f43f5e",
  medium: "#f59e0b",
  low: "#6b7a99",
};

const PRIORITY_LABELS: Priority[] = ["high", "medium", "low"];

let nextId = 50;

export default function Tasks() {
  const [tasks, setTasks] = useState(INIT_TASKS);
  const [input, setInput] = useState("");
  const [newPriority, setNewPriority] = useState<Priority>("medium");
  const [editId, setEditId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [filter, setFilter] = useState<"all" | Priority>("all");

  const addTask = () => {
    if (!input.trim()) return;
    setTasks((t) => [...t, { id: nextId++, text: input.trim(), done: false, priority: newPriority }]);
    setInput("");
  };

  const toggle = (id: number) =>
    setTasks((t) => t.map((x) => (x.id === id ? { ...x, done: !x.done } : x)));

  const remove = (id: number) => setTasks((t) => t.filter((x) => x.id !== id));

  const setPriority = (id: number, priority: Priority) =>
    setTasks((t) => t.map((x) => (x.id === id ? { ...x, priority } : x)));

  const commitEdit = (id: number) => {
    if (editText.trim()) setTasks((t) => t.map((x) => (x.id === id ? { ...x, text: editText.trim() } : x)));
    setEditId(null);
  };

  const filtered = tasks.filter((t) => filter === "all" || t.priority === filter);
  const pending = filtered.filter((t) => !t.done);
  const done = filtered.filter((t) => t.done);

  return (
    <div className="p-6 max-w-2xl" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold" style={{ fontFamily: "'Outfit', sans-serif", color: "#f0f2f7", letterSpacing: "-0.01em" }}>
          Tasks
        </h1>
        {/* Filter */}
        <div className="flex items-center gap-1">
          {(["all", "high", "medium", "low"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className="px-2.5 py-1 rounded-md text-xs font-medium capitalize transition-all"
              style={{
                background: filter === f ? (f === "all" ? "rgba(124,90,246,0.15)" : `${PRIORITY_COLORS[f as Priority]}18`) : "transparent",
                color: filter === f ? (f === "all" ? "#7c5af6" : PRIORITY_COLORS[f as Priority]) : "#6b7a99",
                border: `1px solid ${filter === f ? (f === "all" ? "rgba(124,90,246,0.25)" : `${PRIORITY_COLORS[f as Priority]}30`) : "transparent"}`,
              }}
            >
              {f === "all" ? "All" : (
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: PRIORITY_COLORS[f as Priority] }} />
                  {f}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Add input */}
      <div className="rounded-xl mb-5 overflow-hidden" style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="flex items-center gap-3 px-4 py-3">
          <span style={{ color: "#3d4a63" }}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <line x1="7" y1="1" x2="7" y2="13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <line x1="1" y1="7" x2="13" y2="7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </span>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addTask()}
            placeholder="Add a task and press Enter…"
            className="flex-1 bg-transparent text-sm outline-none"
            style={{ color: "#e8ecf5" }}
          />
        </div>
        {/* Priority picker */}
        <div className="flex items-center gap-2 px-4 pb-3">
          <span className="text-xs" style={{ color: "#3d4a63" }}>Priority:</span>
          {PRIORITY_LABELS.map((p) => (
            <button
              key={p}
              onClick={() => setNewPriority(p)}
              className="flex items-center gap-1.5 px-2 py-0.5 rounded text-xs capitalize transition-all"
              style={{
                background: newPriority === p ? `${PRIORITY_COLORS[p]}18` : "transparent",
                color: newPriority === p ? PRIORITY_COLORS[p] : "#3d4a63",
                border: `1px solid ${newPriority === p ? `${PRIORITY_COLORS[p]}40` : "transparent"}`,
              }}
            >
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: PRIORITY_COLORS[p] }} />
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Pending tasks */}
      {pending.length > 0 && (
        <div className="rounded-xl overflow-hidden mb-4" style={{ border: "1px solid rgba(255,255,255,0.06)", background: "#0e1320" }}>
          {pending.map((task, i) => (
            <div
              key={task.id}
              className="flex items-center gap-3 px-4 py-3 group transition-colors"
              style={{ borderBottom: i < pending.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.02)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <button
                onClick={() => toggle(task.id)}
                className="w-4 h-4 rounded border shrink-0 transition-colors"
                style={{ borderColor: "rgba(255,255,255,0.15)", background: "transparent" }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = PRIORITY_COLORS[task.priority])}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.15)")}
              />

              {/* Priority dot — clickable to cycle */}
              <button
                onClick={() => {
                  const idx = PRIORITY_LABELS.indexOf(task.priority);
                  setPriority(task.id, PRIORITY_LABELS[(idx + 1) % PRIORITY_LABELS.length]);
                }}
                className="w-2 h-2 rounded-full shrink-0 transition-transform"
                style={{ background: PRIORITY_COLORS[task.priority] }}
                title={`Priority: ${task.priority} (click to change)`}
                onMouseEnter={(e) => ((e.target as HTMLElement).style.transform = "scale(1.5)")}
                onMouseLeave={(e) => ((e.target as HTMLElement).style.transform = "scale(1)")}
              />

              {editId === task.id ? (
                <input
                  autoFocus
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") commitEdit(task.id); if (e.key === "Escape") setEditId(null); }}
                  onBlur={() => commitEdit(task.id)}
                  className="flex-1 bg-transparent text-sm outline-none"
                  style={{ color: "#e8ecf5", borderBottom: "1px solid rgba(124,90,246,0.4)" }}
                />
              ) : (
                <span
                  className="flex-1 text-sm cursor-text"
                  style={{ color: "#c4cdd8" }}
                  onDoubleClick={() => { setEditId(task.id); setEditText(task.text); }}
                  title="Double-click to edit"
                >
                  {task.text}
                </span>
              )}

              <button
                onClick={() => remove(task.id)}
                className="opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ color: "#3d4a63" }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "#f43f5e")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "#3d4a63")}
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}

      {pending.length === 0 && (
        <div className="rounded-xl px-4 py-6 text-center text-sm mb-4"
          style={{ border: "1px solid rgba(255,255,255,0.06)", color: "#3d4a63", background: "#0e1320" }}>
          No tasks yet — add one above.
        </div>
      )}

      {/* Done tasks */}
      {done.length > 0 && (
        <div>
          <div className="text-xs font-semibold tracking-widest uppercase mb-2"
            style={{ color: "#3d4a63", letterSpacing: "0.1em" }}>
            Completed ({done.length})
          </div>
          <div className="rounded-xl overflow-hidden" style={{ border: "1px solid rgba(255,255,255,0.04)", background: "#0a0e1a" }}>
            {done.map((task, i) => (
              <div key={task.id} className="flex items-center gap-3 px-4 py-2.5 group"
                style={{ borderBottom: i < done.length - 1 ? "1px solid rgba(255,255,255,0.03)" : "none" }}>
                <button
                  onClick={() => toggle(task.id)}
                  className="w-4 h-4 rounded border shrink-0 flex items-center justify-center"
                  style={{ borderColor: "#10b981", background: "rgba(16,185,129,0.15)" }}
                >
                  <svg width="9" height="9" viewBox="0 0 9 9" fill="none">
                    <path d="M1.5 4.5l2 2 4-4" stroke="#10b981" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: "#2d3a54" }} />
                <span className="flex-1 text-sm line-through" style={{ color: "#3d4a63" }}>{task.text}</span>
                <button
                  onClick={() => remove(task.id)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ color: "#3d4a63" }}
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
