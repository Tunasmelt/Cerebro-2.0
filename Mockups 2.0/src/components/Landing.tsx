import { useState, useEffect } from "react";

interface Props {
  onSignIn: () => void;
  onTryIt: () => void;
}

function GraphNode({ x, y, color, size = 8, delay = 0 }: { x: number; y: number; color: string; size?: number; delay?: number }) {
  return (
    <g transform={`translate(${x},${y})`}>
      <circle r={size + 6} fill={color} opacity={0.08} style={{ animation: `pulse-ring 3s ease-out ${delay}s infinite` }} />
      <circle r={size} fill={color} opacity={0.9} />
      <circle r={size * 0.4} fill="white" opacity={0.6} />
    </g>
  );
}

function ConstellationGraph() {
  const nodes = [
    { x: 120, y: 80, color: "#7c5af6", size: 10 },
    { x: 280, y: 40, color: "#22d3ee", size: 7, delay: 0.5 },
    { x: 340, y: 120, color: "#7c5af6", size: 12 },
    { x: 200, y: 160, color: "#22d3ee", size: 6, delay: 1 },
    { x: 80, y: 180, color: "#7c5af6", size: 8, delay: 1.5 },
    { x: 420, y: 60, color: "#22d3ee", size: 9, delay: 0.8 },
    { x: 460, y: 180, color: "#7c5af6", size: 6, delay: 0.3 },
    { x: 300, y: 220, color: "#22d3ee", size: 8, delay: 1.2 },
    { x: 150, y: 260, color: "#7c5af6", size: 5, delay: 0.7 },
    { x: 380, y: 280, color: "#22d3ee", size: 7, delay: 1.8 },
  ];

  const edges = [
    [0, 1], [1, 2], [2, 3], [3, 0], [4, 0], [2, 5],
    [5, 6], [6, 7], [7, 3], [8, 4], [8, 3], [9, 7],
  ];

  return (
    <svg viewBox="0 0 540 320" className="w-full h-full" style={{ maxHeight: 360 }}>
      <defs>
        <radialGradient id="glow-violet" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#7c5af6" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#7c5af6" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="glow-cyan" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.25" />
          <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
        </radialGradient>
      </defs>
      {/* Ambient glows */}
      <ellipse cx="300" cy="160" rx="200" ry="140" fill="url(#glow-violet)" />
      <ellipse cx="150" cy="80" rx="120" ry="80" fill="url(#glow-cyan)" />

      {/* Edges */}
      {edges.map(([a, b], i) => (
        <line
          key={i}
          x1={nodes[a].x} y1={nodes[a].y}
          x2={nodes[b].x} y2={nodes[b].y}
          stroke="rgba(255,255,255,0.08)"
          strokeWidth="1"
        />
      ))}

      {/* Nodes */}
      {nodes.map((n, i) => (
        <GraphNode key={i} {...n} />
      ))}

      {/* Stars */}
      {[...Array(40)].map((_, i) => (
        <circle
          key={`s${i}`}
          cx={(i * 137.5) % 540}
          cy={(i * 97.3 + 20) % 320}
          r={i % 3 === 0 ? 1.2 : 0.7}
          fill="white"
          opacity={0.15 + (i % 5) * 0.05}
          style={{ animation: `twinkle ${2 + (i % 4)}s ease-in-out ${i * 0.3}s infinite` }}
        />
      ))}
    </svg>
  );
}

export default function Landing({ onSignIn, onTryIt }: Props) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handler);
    return () => window.removeEventListener("scroll", handler);
  }, []);

  return (
    <div className="min-h-screen" style={{ background: "#080b12", fontFamily: "'DM Sans', sans-serif" }}>
      {/* Nav */}
      <nav
        className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-8 h-14 transition-all duration-300"
        style={{
          background: scrolled ? "rgba(8,11,18,0.9)" : "transparent",
          backdropFilter: scrolled ? "blur(12px)" : "none",
          borderBottom: scrolled ? "1px solid rgba(255,255,255,0.06)" : "none",
        }}
      >
        <div className="flex items-center gap-2">
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
            <circle cx="6" cy="11" r="3" fill="#7c5af6" />
            <circle cx="16" cy="6" r="2.5" fill="#22d3ee" />
            <circle cx="16" cy="16" r="2" fill="#7c5af6" opacity="0.7" />
            <line x1="9" y1="11" x2="13.5" y2="7" stroke="rgba(255,255,255,0.3)" strokeWidth="1" />
            <line x1="9" y1="11" x2="13.5" y2="15" stroke="rgba(255,255,255,0.3)" strokeWidth="1" />
          </svg>
          <span style={{ fontFamily: "'Outfit', sans-serif", fontWeight: 700, fontSize: 17, letterSpacing: "-0.01em", color: "#e8ecf5" }}>
            Cerebro
          </span>
        </div>
        <div className="flex items-center gap-6">
          <button
            className="text-sm transition-colors"
            style={{ color: "#6b7a99", fontWeight: 500 }}
            onClick={() => document.getElementById("features")?.scrollIntoView({ behavior: "smooth" })}
            onMouseEnter={(e) => (e.currentTarget.style.color = "#c4cdd8")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "#6b7a99")}
          >
            Features
          </button>
          <button
            className="text-sm transition-colors"
            style={{ color: "#6b7a99", fontWeight: 500 }}
            onClick={onSignIn}
          >
            Sign in
          </button>
          <button
            onClick={onTryIt}
            className="text-sm px-4 py-1.5 rounded-md font-medium transition-all"
            style={{ background: "#7c5af6", color: "#fff", fontWeight: 600 }}
          >
            Try it
          </button>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative pt-28 pb-24 px-8 overflow-hidden">
        {/* Background radial */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: "radial-gradient(ellipse 60% 50% at 65% 40%, rgba(34,211,238,0.06) 0%, transparent 70%), radial-gradient(ellipse 50% 60% at 30% 60%, rgba(124,90,246,0.08) 0%, transparent 70%)",
          }}
        />

        <div className="relative max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
          <div>
            <div
              className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold mb-8 tracking-widest uppercase"
              style={{ background: "rgba(34,211,238,0.08)", color: "#22d3ee", border: "1px solid rgba(34,211,238,0.15)", letterSpacing: "0.12em" }}
            >
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#22d3ee" }} />
              Personal Knowledge Vault
            </div>

            <h1
              className="mb-6 leading-none"
              style={{
                fontFamily: "'Outfit', sans-serif",
                fontSize: "clamp(2.8rem, 6vw, 4.5rem)",
                fontWeight: 800,
                color: "#f0f2f7",
                letterSpacing: "-0.03em",
                lineHeight: 1.0,
              }}
            >
              Your documents,<br />
              as a{" "}
              <span style={{ color: "#7c5af6" }}>graph</span>{" "}
              you<br />
              can query.
            </h1>

            <p className="mb-10 text-base leading-relaxed" style={{ color: "#6b7a99", maxWidth: 420, fontWeight: 400 }}>
              Ask a question in plain language. Cerebro retrieves the exact nodes it used
              to answer — not a black box, not a decorative animation.
            </p>

            <div className="flex items-center gap-4">
              <button
                onClick={onTryIt}
                className="px-6 py-3 rounded-lg font-semibold text-sm transition-all"
                style={{ background: "#7c5af6", color: "#fff", boxShadow: "0 0 32px rgba(124,90,246,0.35)" }}
              >
                Try it free
              </button>
              <button
                onClick={onSignIn}
                className="px-6 py-3 rounded-lg font-medium text-sm transition-all"
                style={{ color: "#6b7a99", border: "1px solid rgba(255,255,255,0.08)" }}
              >
                Sign in
              </button>
            </div>
          </div>

          <div className="relative animate-float">
            <div
              className="rounded-2xl overflow-hidden p-4"
              style={{
                background: "rgba(14,19,32,0.6)",
                border: "1px solid rgba(255,255,255,0.07)",
                backdropFilter: "blur(12px)",
              }}
            >
              <ConstellationGraph />
            </div>
          </div>
        </div>
      </section>

      {/* Divider */}
      <div style={{ height: 1, background: "rgba(255,255,255,0.04)", margin: "0 2rem" }} />

      {/* Feature 01 */}
      <section className="py-24 px-8">
        <div className="max-w-6xl mx-auto">
          <div className="mb-16">
            <span className="text-xs font-mono tracking-widest" style={{ color: "#22d3ee", fontFamily: "'JetBrains Mono', monospace" }}>01</span>
            <h2 className="mt-3 text-3xl font-bold" style={{ fontFamily: "'Outfit', sans-serif", color: "#f0f2f7", letterSpacing: "-0.02em" }}>
              Ask it anything you've stored
            </h2>
            <p className="mt-3 text-sm" style={{ color: "#6b7a99", maxWidth: 480, lineHeight: 1.7 }}>
              Every answer is grounded in nodes from your own vault, with citations back to source.
            </p>
          </div>

          <div
            className="rounded-xl overflow-hidden"
            style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)" }}
          >
            {/* Mock chat interface */}
            <div className="p-6">
              <div className="flex justify-center mb-6">
                <div
                  className="px-5 py-3 rounded-lg text-sm"
                  style={{ background: "rgba(124,90,246,0.15)", color: "#c4b5fd", border: "1px solid rgba(124,90,246,0.2)" }}
                >
                  What did I read about consensus algorithms last spring?
                </div>
              </div>
              <div
                className="rounded-lg p-5 text-sm leading-relaxed"
                style={{ background: "#141b2d", color: "#9aa5bc", lineHeight: 1.7 }}
              >
                You went through three papers on Raft and Paxos between March and April{" "}
                <span className="px-1.5 py-0.5 rounded text-xs font-mono" style={{ background: "rgba(34,211,238,0.12)", color: "#22d3ee" }}>[1]</span>{" "}
                <span className="px-1.5 py-0.5 rounded text-xs font-mono" style={{ background: "rgba(34,211,238,0.12)", color: "#22d3ee" }}>[2]</span>,
                and your own notes flag Raft as easier to reason about for small clusters{" "}
                <span className="px-1.5 py-0.5 rounded text-xs font-mono" style={{ background: "rgba(34,211,238,0.12)", color: "#22d3ee" }}>[3]</span>.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features section */}
      <section id="features" className="py-24 px-8" style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
        <div className="max-w-6xl mx-auto">
          <div className="mb-4 text-xs tracking-widest font-semibold uppercase" style={{ color: "#6b7a99", letterSpacing: "0.12em" }}>
            Features
          </div>
          <h2
            className="mb-20 text-4xl font-bold"
            style={{ fontFamily: "'Outfit', sans-serif", color: "#f0f2f7", letterSpacing: "-0.02em" }}
          >
            How Cerebro actually works.
          </h2>

          <div className="space-y-24">
            {/* Feature 01 */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
              <div
                className="rounded-xl aspect-video flex items-center justify-center"
                style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)" }}
              >
                <svg width="160" height="100" viewBox="0 0 160 100">
                  <circle cx="40" cy="50" r="10" fill="#7c5af6" opacity="0.9" />
                  <circle cx="100" cy="30" r="7" fill="#22d3ee" opacity="0.9" />
                  <circle cx="130" cy="65" r="8" fill="#7c5af6" opacity="0.7" />
                  <line x1="50" y1="50" x2="93" y2="33" stroke="rgba(255,255,255,0.15)" strokeWidth="1.5" />
                  <line x1="107" y1="35" x2="122" y2="58" stroke="rgba(255,255,255,0.15)" strokeWidth="1.5" />
                </svg>
              </div>
              <div>
                <div className="text-xs font-mono mb-3" style={{ color: "#22d3ee", fontFamily: "'JetBrains Mono', monospace" }}>
                  01 · INGEST
                </div>
                <h3 className="text-xl font-semibold mb-4" style={{ color: "#f0f2f7", fontFamily: "'Outfit', sans-serif" }}>
                  One index for documents and images
                </h3>
                <p className="text-sm leading-relaxed" style={{ color: "#6b7a99", lineHeight: 1.75 }}>
                  Drop in PDFs, notes, and photos of whiteboards or printed pages — they all land in the same graph.
                  Cerebro reads text and images alike, so a scanned diagram and a typed note can end up in the same
                  retrieved cluster.
                </p>
              </div>
            </div>

            {/* Feature 02 */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
              <div className="lg:order-2">
                <div
                  className="rounded-xl p-6"
                  style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.07)" }}
                >
                  {[
                    { label: "vector", width: "72%", color: "#7c5af6" },
                    { label: "full-text", width: "55%", color: "#22d3ee" },
                    { label: "ranked", width: "85%", color: "rgba(255,255,255,0.25)" },
                  ].map((row) => (
                    <div key={row.label} className="flex items-center gap-4 mb-4 last:mb-0">
                      <div className="text-xs font-mono w-16 text-right shrink-0" style={{ color: "#6b7a99", fontFamily: "'JetBrains Mono', monospace" }}>
                        {row.label}
                      </div>
                      <div className="flex-1 h-1.5 rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                        <div
                          className="h-full rounded-full transition-all"
                          style={{ width: row.width, background: row.color }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="lg:order-1">
                <div className="text-xs font-mono mb-3" style={{ color: "#22d3ee", fontFamily: "'JetBrains Mono', monospace" }}>
                  02 · RETRIEVAL
                </div>
                <h3 className="text-xl font-semibold mb-4" style={{ color: "#f0f2f7", fontFamily: "'Outfit', sans-serif" }}>
                  Search finds it two ways, then merges
                </h3>
                <p className="text-sm leading-relaxed" style={{ color: "#6b7a99", lineHeight: 1.75 }}>
                  Every query runs as both a meaning-based vector search and a plain keyword search. The two result lists
                  get merged into a single ranking, so an exact term match and a conceptually related note can both
                  surface — whichever actually answers you.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-8 text-center" style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
        <div className="max-w-xl mx-auto">
          <h2
            className="text-4xl font-bold mb-4"
            style={{ fontFamily: "'Outfit', sans-serif", color: "#f0f2f7", letterSpacing: "-0.02em" }}
          >
            Your knowledge, finally queryable.
          </h2>
          <p className="text-sm mb-8" style={{ color: "#6b7a99", lineHeight: 1.7 }}>
            Connect your documents, notes, and images. Start asking questions in seconds.
          </p>
          <button
            onClick={onTryIt}
            className="px-8 py-3.5 rounded-lg font-semibold text-sm"
            style={{ background: "#7c5af6", color: "#fff", boxShadow: "0 0 40px rgba(124,90,246,0.4)" }}
          >
            Get started free
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-8 py-8" style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <span style={{ fontFamily: "'Outfit', sans-serif", fontWeight: 700, fontSize: 15, color: "#3d4a63" }}>Cerebro</span>
          <span className="text-xs" style={{ color: "#3d4a63" }}>
            © 2026 Cerebro. Personal Knowledge Vault.
          </span>
        </div>
      </footer>
    </div>
  );
}
