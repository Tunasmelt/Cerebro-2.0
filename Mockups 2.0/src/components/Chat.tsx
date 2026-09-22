import { useState, useRef, useEffect } from "react";

interface Message {
  role: "user" | "ai";
  text: string;
  citations?: string[];
}

interface ChatSession {
  id: number;
  title: string;
  date: string;
  preview: string;
  messages: Message[];
}

const INITIAL_SESSIONS: ChatSession[] = [
  {
    id: 1,
    title: "Conclusion on the two IR papers",
    date: "Sep 13, 12:16 AM",
    preview: "The provided text chunks consist of bibliographical references...",
    messages: [
      { role: "user", text: "Conclusion on the two IR papers" },
      {
        role: "ai",
        text: 'The provided text chunks consist of bibliographical references and citations from two different sources ("BrightPro Paper" and "IR Misses the Mark"). They list various academic papers, preprints, and datasets related to information retrieval, language models, retrieval-augmented generation (RAG), and benchmarking (such as BRIGHT, BEIR, MS MARCO, and Coveragebench). Because the context only contains these reference lists and lacks the main body, analysis, or conclusion sections of the papers, a substantive conclusion about the findings or arguments of the two IR papers cannot be drawn from the provided text.',
        citations: ["#1", "#2", "#3", "#4", "#5"],
      },
    ],
  },
  {
    id: 2,
    title: "Similarities in IR Paper and BrightPro",
    date: "Sep 8, 4:02 PM",
    preview: "Both papers focus on retrieval-augmented approaches...",
    messages: [
      { role: "user", text: "What are the similarities between the IR Paper and BrightPro?" },
      { role: "ai", text: "Both papers focus on retrieval-augmented approaches and dense embedding techniques. BrightPro emphasizes cross-modal retrieval while the IR paper concentrates on sparse-dense hybrid methods.", citations: ["#1", "#2"] },
    ],
  },
  {
    id: 3,
    title: "Tell me about PyPI-Recovery",
    date: "Sep 7, 6:22 PM",
    preview: "PyPI Recovery is a sealed document in your vault...",
    messages: [
      { role: "user", text: "Tell me about PyPI Recovery" },
      { role: "ai", text: "This document is sealed and its contents cannot be retrieved without decryption. It was uploaded on September 5, 2026.", citations: [] },
    ],
  },
  {
    id: 4,
    title: "Tell me about IR Misses the Mark",
    date: "Sep 7, 1:57 PM",
    preview: "IR Misses the Mark argues that current benchmarks fail...",
    messages: [
      { role: "user", text: "Tell me about IR Misses the Mark" },
      { role: "ai", text: "IR Misses the Mark argues that current information retrieval benchmarks fail to capture real-world retrieval complexity. The paper proposes new evaluation criteria based on reasoning-intensive retrieval tasks.", citations: ["#1"] },
    ],
  },
  {
    id: 5,
    title: "Explain the forked rap architecture",
    date: "Sep 5, 1:14 PM",
    preview: "The ForkedRap architecture uses a layer-based approach...",
    messages: [
      { role: "user", text: "Explain me the forked rap architecture" },
      { role: "ai", text: "The ForkedRap architecture uses a layer-based approach where Layer 1 handles raw data ingestion and normalization. Subsequent layers perform entity extraction, relationship mapping, and graph construction.", citations: ["#1"] },
    ],
  },
  {
    id: 6,
    title: "Tell me about Junior IT Specialist",
    date: "Sep 4, 3:20 AM",
    preview: "Outlines a job description for a technical support role...",
    messages: [
      { role: "user", text: "Tell me about Junior IT Specialist" },
      { role: "ai", text: "The Junior IT Specialist document outlines a job description for a technical support role, including responsibilities for network maintenance, hardware troubleshooting, and software deployment.", citations: ["#1"] },
    ],
  },
  {
    id: 7,
    title: "Tell me about Yaras Schedule",
    date: "Sep 4, 3:18 AM",
    preview: "An image showing a weekly timetable...",
    messages: [
      { role: "user", text: "Tell me about Yaras Schedule" },
      { role: "ai", text: "Yaras Schedule is an image file showing a weekly timetable. From the image, it appears to contain class times, study blocks, and personal appointments arranged in a grid format.", citations: ["#1"] },
    ],
  },
];

const STUB_REPLIES = [
  "Based on the documents in your vault, I found several relevant nodes. The answer spans across multiple sources — here's a synthesis.",
  "I searched your vault and retrieved 3 relevant chunks. The most pertinent comes from a document uploaded on Sep 7.",
  "Your vault contains related content in the BrightPro Paper and the IR Misses the Mark document. Let me summarize what they say about this.",
  "I found a match in the ForkedRap Architecture notes. The relevant section discusses this concept in detail.",
];

let nextId = 100;

export default function Chat() {
  const [sessions, setSessions] = useState(INITIAL_SESSIONS);
  const [activeId, setActiveId] = useState(1);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const active = sessions.find((s) => s.id === activeId)!;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active?.messages.length, thinking]);

  const send = () => {
    const text = input.trim();
    if (!text || thinking) return;
    setInput("");

    setSessions((prev) =>
      prev.map((s) =>
        s.id === activeId
          ? { ...s, messages: [...s.messages, { role: "user", text }] }
          : s
      )
    );

    setThinking(true);
    setTimeout(() => {
      const reply = STUB_REPLIES[Math.floor(Math.random() * STUB_REPLIES.length)];
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeId
            ? {
                ...s,
                preview: reply.slice(0, 60) + "...",
                messages: [
                  ...s.messages,
                  { role: "ai", text: reply, citations: ["#1", "#2"] },
                ],
              }
            : s
        )
      );
      setThinking(false);
    }, 1200 + Math.random() * 800);
  };

  const newChat = () => {
    const id = nextId++;
    const session: ChatSession = {
      id,
      title: "New conversation",
      date: new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
      preview: "Start by asking a question about your documents.",
      messages: [],
    };
    setSessions((prev) => [session, ...prev]);
    setActiveId(id);
  };

  const deleteSession = (id: number) => {
    const remaining = sessions.filter((s) => s.id !== id);
    setSessions(remaining);
    if (activeId === id) setActiveId(remaining[0]?.id ?? -1);
  };

  return (
    <div className="flex h-full" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      {/* Session list */}
      <div className="w-64 shrink-0 flex flex-col overflow-hidden" style={{ borderRight: "1px solid rgba(255,255,255,0.05)" }}>
        <div className="flex items-center justify-between px-3 py-2.5" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
          <span className="text-xs font-semibold tracking-widest uppercase" style={{ color: "#3d4a63", letterSpacing: "0.1em" }}>
            Chats
          </span>
          <button
            onClick={newChat}
            className="w-6 h-6 rounded-md flex items-center justify-center transition-colors"
            style={{ color: "#6b7a99", background: "rgba(255,255,255,0.04)" }}
            title="New chat"
            onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(124,90,246,0.15)"; e.currentTarget.style.color = "#7c5af6"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; e.currentTarget.style.color = "#6b7a99"; }}
          >
            <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
              <line x1="5.5" y1="1" x2="5.5" y2="10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <line x1="1" y1="5.5" x2="10" y2="5.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto py-1">
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => setActiveId(s.id)}
              className="w-full text-left px-3 py-2.5 group relative transition-colors"
              style={{
                background: activeId === s.id ? "rgba(124,90,246,0.08)" : "transparent",
                borderLeft: `2px solid ${activeId === s.id ? "#7c5af6" : "transparent"}`,
              }}
              onMouseEnter={(e) => { if (activeId !== s.id) e.currentTarget.style.background = "rgba(255,255,255,0.03)"; }}
              onMouseLeave={(e) => { if (activeId !== s.id) e.currentTarget.style.background = "transparent"; }}
            >
              <div className="flex items-start justify-between gap-1 mb-0.5">
                <span className="text-sm font-medium truncate" style={{ color: activeId === s.id ? "#e8ecf5" : "#9aa5bc", maxWidth: 150 }}>
                  {s.title}
                </span>
                <button
                  onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                  className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded"
                  style={{ color: "#3d4a63" }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = "#f43f5e")}
                  onMouseLeave={(e) => (e.currentTarget.style.color = "#3d4a63")}
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                    <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
              <div className="text-xs mb-0.5" style={{ color: "#3d4a63" }}>{s.date}</div>
              <div className="text-xs truncate" style={{ color: "#3d4a63", maxWidth: 190 }}>{s.preview}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Conversation */}
      {active ? (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3 shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
            <span className="text-xs font-mono" style={{ color: "#6b7a99", fontFamily: "'JetBrains Mono', monospace" }}>
              {active.date}
            </span>
            <button
              className="text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
              style={{ background: "rgba(255,255,255,0.05)", color: "#6b7a99", border: "1px solid rgba(255,255,255,0.07)" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.08)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.05)")}
            >
              Export
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
            {active.messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <div className="w-10 h-10 rounded-xl mb-3 flex items-center justify-center" style={{ background: "rgba(124,90,246,0.12)" }}>
                  <svg width="18" height="18" viewBox="0 0 15 15" fill="none">
                    <path d="M2 2.5h11a.5.5 0 01.5.5v7a.5.5 0 01-.5.5H5L2 13V3a.5.5 0 01.5-.5z" stroke="#7c5af6" strokeWidth="1.2" strokeLinejoin="round" />
                  </svg>
                </div>
                <p className="text-sm font-medium mb-1" style={{ color: "#6b7a99" }}>New conversation</p>
                <p className="text-xs" style={{ color: "#3d4a63" }}>Ask anything about your documents</p>
              </div>
            )}

            {active.messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                {msg.role === "user" ? (
                  <div className="max-w-sm px-4 py-2.5 rounded-2xl rounded-tr-sm text-sm font-medium"
                    style={{ background: "#7c5af6", color: "#fff" }}>
                    {msg.text}
                  </div>
                ) : (
                  <div className="max-w-2xl rounded-2xl rounded-tl-sm p-5 text-sm leading-relaxed"
                    style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)", color: "#9aa5bc", lineHeight: 1.75 }}>
                    {msg.text}
                    {msg.citations && msg.citations.length > 0 && (
                      <span className="ml-1">
                        {msg.citations.map((c, j) => (
                          <span key={j}
                            className="inline-flex items-center justify-center rounded px-1.5 py-0.5 text-xs font-mono mx-0.5 cursor-pointer transition-colors"
                            style={{ background: "rgba(34,211,238,0.1)", color: "#22d3ee", fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }}
                            title={`Source ${c}`}
                          >
                            {c}
                          </span>
                        ))}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}

            {/* Thinking indicator */}
            {thinking && (
              <div className="flex justify-start">
                <div className="px-5 py-4 rounded-2xl rounded-tl-sm flex items-center gap-2"
                  style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)" }}>
                  {[0, 1, 2].map((i) => (
                    <span key={i} className="w-1.5 h-1.5 rounded-full"
                      style={{
                        background: "#7c5af6",
                        animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
                        display: "inline-block",
                      }}
                    />
                  ))}
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="px-6 pb-5 shrink-0">
            <div className="flex items-center gap-3 rounded-xl px-4 py-3"
              style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.08)" }}>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder="Ask a follow-up…"
                className="flex-1 bg-transparent text-sm outline-none"
                style={{ color: "#e8ecf5" }}
                disabled={thinking}
              />
              <button
                onClick={send}
                disabled={!input.trim() || thinking}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-opacity"
                style={{ background: "#7c5af6", color: "#fff", opacity: input.trim() && !thinking ? 1 : 0.4, cursor: input.trim() && !thinking ? "pointer" : "default" }}
              >
                Send
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <button onClick={newChat} className="text-sm px-4 py-2 rounded-lg" style={{ background: "rgba(124,90,246,0.12)", color: "#7c5af6" }}>
            Start a new chat
          </button>
        </div>
      )}

      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
          40% { transform: translateY(-5px); opacity: 1; }
        }
      `}</style>
    </div>
  );
}
