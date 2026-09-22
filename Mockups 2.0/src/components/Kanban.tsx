import { useState } from "react";

interface Card {
  id: number;
  title: string;
  desc: string;
}

interface Column {
  id: string;
  label: string;
  color: string;
  cards: Card[];
}

const INITIAL_COLUMNS: Column[] = [
  {
    id: "backlog",
    label: "Backlog",
    color: "#7c5af6",
    cards: [
      { id: 1, title: "Brush teeth and basic things", desc: "6:30–7:00 am, brush ur teeth, basic things yk" },
      { id: 2, title: "Do online classes", desc: "9:00 am–04:00 pm, do ur online classes" },
      { id: 3, title: "Build Schema and Core Tables", desc: "Create the database tables for fetch_sessions, staging_feed, and raw_feed as the foundational step." },
    ],
  },
  {
    id: "inprogress",
    label: "In Progress",
    color: "#22d3ee",
    cards: [
      { id: 4, title: "Go and jog/exercise", desc: "7:00–8:00 am, go and jog/exercise" },
      { id: 5, title: "Freshen up and get ready for classes", desc: "8:00–9:00 am, freshen up and get ready for classes" },
      { id: 6, title: "Wake up", desc: "6:30 am, wake up" },
    ],
  },
  {
    id: "done",
    label: "Done",
    color: "#f59e0b",
    cards: [
      { id: 7, title: "Study", desc: "05:00–07:00 pm, study!" },
    ],
  },
];

const AGENT_RESPONSES: Record<string, { title: string; desc: string; col: string }> = {
  exercise: { title: "Morning run", desc: "7:00–8:00 am, 30-minute jog around the block", col: "backlog" },
  study: { title: "Review lecture notes", desc: "6:00–7:00 pm, go over today's material", col: "backlog" },
  meeting: { title: "Team standup", desc: "9:00 am, 15-minute sync with the group", col: "inprogress" },
  dinner: { title: "Cook dinner", desc: "7:00 pm, prepare a healthy meal", col: "backlog" },
  read: { title: "Reading session", desc: "9:00–10:00 pm, read one chapter", col: "backlog" },
};

let nextId = 100;

export default function Kanban() {
  const [columns, setColumns] = useState(INITIAL_COLUMNS);
  const [query, setQuery] = useState("");
  const [agentResponse, setAgentResponse] = useState<string | null>(null);
  const [newCardCol, setNewCardCol] = useState<string | null>(null);
  const [newCardTitle, setNewCardTitle] = useState("");
  const [editCard, setEditCard] = useState<{ colId: string; cardId: number } | null>(null);

  const deleteCard = (colId: string, cardId: number) => {
    setColumns((cols) => cols.map((c) => c.id === colId ? { ...c, cards: c.cards.filter((x) => x.id !== cardId) } : c));
  };

  const addCard = (colId: string) => {
    if (!newCardTitle.trim()) return;
    const card: Card = { id: nextId++, title: newCardTitle.trim(), desc: "" };
    setColumns((cols) => cols.map((c) => c.id === colId ? { ...c, cards: [...c.cards, card] } : c));
    setNewCardTitle("");
    setNewCardCol(null);
  };

  const moveCard = (fromCol: string, toCol: string, cardId: number) => {
    let card: Card | undefined;
    const withoutCard = columns.map((c) => {
      if (c.id !== fromCol) return c;
      card = c.cards.find((x) => x.id === cardId);
      return { ...c, cards: c.cards.filter((x) => x.id !== cardId) };
    });
    if (!card) return;
    const finalCard = card;
    setColumns(withoutCard.map((c) => c.id === toCol ? { ...c, cards: [...c.cards, finalCard] } : c));
  };

  const askAgent = () => {
    const q = query.toLowerCase();
    const match = Object.entries(AGENT_RESPONSES).find(([key]) => q.includes(key));
    if (match) {
      const { title, desc, col } = match[1];
      const card: Card = { id: nextId++, title, desc };
      setColumns((cols) => cols.map((c) => c.id === col ? { ...c, cards: [...c.cards, card] } : c));
      setAgentResponse(`Added "${title}" to ${col === "inprogress" ? "In Progress" : col.charAt(0).toUpperCase() + col.slice(1)}.`);
    } else {
      setAgentResponse("I couldn't parse that as a task. Try something like \"add a meeting\" or \"add study time\".");
    }
    setQuery("");
    setTimeout(() => setAgentResponse(null), 3500);
  };

  return (
    <div className="p-6 h-full flex flex-col" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold" style={{ fontFamily: "'Outfit', sans-serif", color: "#f0f2f7", letterSpacing: "-0.01em" }}>
          My Board
        </h1>
        <div className="flex items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && query.trim() && askAgent()}
            placeholder="Ask the agent to add a card…"
            className="text-sm px-3 py-1.5 rounded-lg outline-none"
            style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.08)", color: "#e8ecf5", width: 240 }}
          />
          <button
            onClick={() => query.trim() && askAgent()}
            disabled={!query.trim()}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold transition-opacity"
            style={{ background: "#7c5af6", color: "#fff", opacity: query.trim() ? 1 : 0.4 }}
          >
            Ask
          </button>
        </div>
      </div>

      {/* Agent response toast */}
      {agentResponse && (
        <div
          className="mb-4 px-4 py-2.5 rounded-xl text-sm"
          style={{
            background: "rgba(14,19,32,0.9)",
            border: "1px solid rgba(124,90,246,0.25)",
            color: "#9aa5bc",
            animation: "fade-up 0.2s ease forwards",
          }}
        >
          <span style={{ color: "#7c5af6", marginRight: 8 }}>Agent</span>
          {agentResponse}
        </div>
      )}

      {/* Board */}
      <div className="flex gap-4 flex-1 overflow-x-auto pb-2">
        {columns.map((col) => (
          <div
            key={col.id}
            className="shrink-0 flex flex-col rounded-xl overflow-hidden"
            style={{ width: 280, background: "#0e1320", border: "1px solid rgba(255,255,255,0.06)" }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              const data = e.dataTransfer.getData("text/plain").split(":");
              if (data.length === 2) moveCard(data[0], col.id, parseInt(data[1]));
            }}
          >
            {/* Column header */}
            <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ background: col.color }} />
                <span className="text-sm font-semibold" style={{ color: "#e8ecf5" }}>{col.label}</span>
              </div>
              <span
                className="text-xs font-mono w-5 h-5 rounded flex items-center justify-center"
                style={{ background: "rgba(255,255,255,0.05)", color: "#6b7a99", fontFamily: "'JetBrains Mono', monospace" }}
              >
                {col.cards.length}
              </span>
            </div>

            {/* Cards */}
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {col.cards.map((card) => (
                <div
                  key={card.id}
                  draggable
                  onDragStart={(e) => { e.dataTransfer.setData("text/plain", `${col.id}:${card.id}`); e.currentTarget.style.opacity = "0.5"; }}
                  onDragEnd={(e) => (e.currentTarget.style.opacity = "1")}
                  className="rounded-lg p-3 group relative transition-all cursor-grab active:cursor-grabbing"
                  style={{ background: "#141b2d", border: "1px solid rgba(255,255,255,0.05)" }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.1)")}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.05)")}
                >
                  {editCard?.colId === col.id && editCard.cardId === card.id ? (
                    <input
                      autoFocus
                      defaultValue={card.title}
                      className="w-full bg-transparent text-sm font-medium outline-none pr-5"
                      style={{ color: "#e8ecf5", borderBottom: "1px solid rgba(124,90,246,0.4)" }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          const val = (e.target as HTMLInputElement).value.trim();
                          if (val) {
                            setColumns((cols) => cols.map((c) => c.id === col.id
                              ? { ...c, cards: c.cards.map((x) => x.id === card.id ? { ...x, title: val } : x) }
                              : c
                            ));
                          }
                          setEditCard(null);
                        }
                        if (e.key === "Escape") setEditCard(null);
                      }}
                      onBlur={(e) => {
                        const val = (e.target as HTMLInputElement).value.trim();
                        if (val) setColumns((cols) => cols.map((c) => c.id === col.id
                          ? { ...c, cards: c.cards.map((x) => x.id === card.id ? { ...x, title: val } : x) }
                          : c
                        ));
                        setEditCard(null);
                      }}
                    />
                  ) : (
                    <div
                      className="text-sm font-medium mb-1 pr-5"
                      style={{ color: "#e8ecf5" }}
                      onDoubleClick={() => setEditCard({ colId: col.id, cardId: card.id })}
                      title="Double-click to edit"
                    >
                      {card.title}
                    </div>
                  )}
                  {card.desc && (
                    <div className="text-xs leading-relaxed" style={{ color: "#6b7a99" }}>{card.desc}</div>
                  )}

                  {/* Move buttons — appear on hover */}
                  <div className="absolute top-2 right-7 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    {columns.filter((c) => c.id !== col.id).map((targetCol) => (
                      <button
                        key={targetCol.id}
                        onClick={() => moveCard(col.id, targetCol.id, card.id)}
                        className="w-4 h-4 rounded text-xs flex items-center justify-center"
                        style={{ background: `${targetCol.color}25`, color: targetCol.color }}
                        title={`Move to ${targetCol.label}`}
                      >
                        →
                      </button>
                    ))}
                  </div>

                  <button
                    onClick={() => deleteCard(col.id, card.id)}
                    className="absolute top-2.5 right-2.5 opacity-0 group-hover:opacity-100 transition-opacity"
                    style={{ color: "#3d4a63" }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = "#f43f5e")}
                    onMouseLeave={(e) => (e.currentTarget.style.color = "#3d4a63")}
                  >
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                      <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                    </svg>
                  </button>
                </div>
              ))}

              {/* Add card */}
              {newCardCol === col.id ? (
                <div className="rounded-lg p-2" style={{ background: "#141b2d", border: "1px solid rgba(124,90,246,0.3)" }}>
                  <input
                    autoFocus
                    value={newCardTitle}
                    onChange={(e) => setNewCardTitle(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") addCard(col.id); if (e.key === "Escape") setNewCardCol(null); }}
                    placeholder="Card title…"
                    className="w-full bg-transparent text-sm outline-none"
                    style={{ color: "#e8ecf5" }}
                  />
                  <div className="flex gap-1 mt-2">
                    <button
                      onClick={() => addCard(col.id)}
                      className="text-xs px-2 py-1 rounded font-medium"
                      style={{ background: "#7c5af6", color: "#fff" }}
                    >
                      Add
                    </button>
                    <button onClick={() => setNewCardCol(null)} className="text-xs px-2 py-1 rounded" style={{ color: "#6b7a99" }}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setNewCardCol(col.id)}
                  className="w-full text-left text-sm px-2 py-1.5 rounded-lg transition-colors"
                  style={{ color: "#3d4a63" }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = "#6b7a99")}
                  onMouseLeave={(e) => (e.currentTarget.style.color = "#3d4a63")}
                >
                  + Add card
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
