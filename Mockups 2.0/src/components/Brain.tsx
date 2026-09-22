import { useRef, useEffect, useState, useCallback } from "react";

interface Node {
  id: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  color: string;
  type: "document" | "image" | "sealed";
  label: string;
  size: number;
}

interface Props {
  onNavigate: (view: "chat" | "documents") => void;
}

const DOCS = [
  { label: "Full Stack AI Developer.pdf", type: "document" as const },
  { label: "BrightPro Paper", type: "document" as const },
  { label: "IR Misses the Mark", type: "document" as const },
  { label: "Yaras Schedule", type: "image" as const },
  { label: "ForkedRap Architecture", type: "document" as const },
  { label: "Junior IT Specialist", type: "document" as const },
  { label: "Retention Marketing", type: "document" as const },
  { label: "Screenshot 2026-08-23", type: "image" as const },
  { label: "PyPI Recovery", type: "sealed" as const },
  { label: "Consensus Algorithms", type: "document" as const },
  { label: "87088384.jpg", type: "image" as const },
  { label: "32622956.jpg", type: "image" as const },
];

const COLOR_MAP = { document: "#7c5af6", image: "#22d3ee", sealed: "#f59e0b" };

const EDGES: [number, number][] = [
  [0, 9], [0, 4], [1, 2], [1, 9], [2, 9], [3, 6],
  [4, 5], [5, 6], [7, 3], [8, 0], [10, 7], [11, 10],
];

const REPEL = 4800;
const SPRING_LEN = 160;
const SPRING_K = 0.018;
const DAMPING = 0.82;
const CENTER_PULL = 0.003;

function initNodes(w: number, h: number): Node[] {
  const cx = w / 2, cy = h / 2, r = Math.min(w, h) * 0.32;
  return DOCS.map((d, i) => {
    const angle = (i / DOCS.length) * Math.PI * 2;
    return {
      id: i,
      x: cx + Math.cos(angle) * r * (0.6 + Math.random() * 0.4),
      y: cy + Math.sin(angle) * r * (0.6 + Math.random() * 0.4),
      vx: 0, vy: 0,
      color: COLOR_MAP[d.type],
      type: d.type,
      label: d.label,
      size: d.type === "document" ? 10 : d.type === "image" ? 9 : 7,
    };
  });
}

const STARS = Array.from({ length: 90 }, (_, i) => ({
  x: (i * 137.508) % 1,
  y: (i * 97.319) % 1,
  r: i % 3 === 0 ? 1.2 : 0.7,
  a: 0.1 + (i % 7) * 0.04,
  speed: 2 + (i % 4),
  phase: i * 0.6,
}));

export default function Brain({ onNavigate }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<Node[]>([]);
  const rafRef = useRef<number>(0);
  const tickRef = useRef(0);

  const camRef = useRef({ x: 0, y: 0, scale: 1 });
  const targetCamRef = useRef({ x: 0, y: 0, scale: 1 });

  // Keep latest values in refs so canvas callbacks never need to re-register
  const selectedRef = useRef<Node | null>(null);
  const queryRef = useRef("");

  const [selected, setSelectedState] = useState<Node | null>(null);
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [showLegend, setShowLegend] = useState(true);
  const [askText, setAskText] = useState("");

  const searchRef = useRef<HTMLInputElement>(null);

  const setSelected = useCallback((n: Node | null) => {
    selectedRef.current = n;
    setSelectedState(n);
  }, []);

  const setQueryBoth = useCallback((q: string) => {
    queryRef.current = q;
    setQuery(q);
  }, []);

  const matchesQuery = useCallback(
    (label: string) => queryRef.current.length > 0 && label.toLowerCase().includes(queryRef.current.toLowerCase()),
    []
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement !== searchRef.current) {
        e.preventDefault();
        searchRef.current?.focus();
      }
      if (e.key === "Escape") {
        setQueryBoth("");
        setQueryInput("");
        searchRef.current?.blur();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [setQueryBoth]);

  // Single long-lived canvas loop — no deps that cause re-registration
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;
    let W = 0, H = 0;

    const resize = () => {
      const dpr = devicePixelRatio;
      W = canvas.offsetWidth;
      H = canvas.offsetHeight;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (nodesRef.current.length === 0) {
        nodesRef.current = initNodes(W, H);
        camRef.current = { x: W / 2, y: H / 2, scale: 1 };
        targetCamRef.current = { x: W / 2, y: H / 2, scale: 1 };
      }
    };
    resize();
    window.addEventListener("resize", resize);

    const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

    function draw() {
      tickRef.current++;
      const t = tickRef.current;
      W = canvas!.offsetWidth;
      H = canvas!.offsetHeight;
      ctx.clearRect(0, 0, W, H);

      ctx.fillStyle = "#080b12";
      ctx.fillRect(0, 0, W, H);

      for (const s of STARS) {
        const twinkle = 0.5 + 0.5 * Math.sin(t * 0.01 * (1 / s.speed) + s.phase);
        ctx.beginPath();
        ctx.arc(s.x * W, s.y * H, s.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255,255,255,${s.a * (0.4 + 0.6 * twinkle)})`;
        ctx.fill();
      }

      const cam = camRef.current;
      const tgt = targetCamRef.current;
      cam.x = lerp(cam.x, tgt.x, 0.07);
      cam.y = lerp(cam.y, tgt.y, 0.07);
      cam.scale = lerp(cam.scale, tgt.scale, 0.07);

      const nodes = nodesRef.current;
      const cx = W / 2, cy = H / 2;
      const sel = selectedRef.current;
      const q = queryRef.current;
      const anyMatch = q.length > 0;

      const fx = new Float64Array(nodes.length);
      const fy = new Float64Array(nodes.length);

      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist2 = dx * dx + dy * dy + 1;
          const force = REPEL / dist2;
          const d = Math.sqrt(dist2);
          fx[i] += (dx / d) * force; fy[i] += (dy / d) * force;
          fx[j] -= (dx / d) * force; fy[j] -= (dy / d) * force;
        }
      }

      for (const [a, b] of EDGES) {
        const dx = nodes[b].x - nodes[a].x;
        const dy = nodes[b].y - nodes[a].y;
        const dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
        const force = (dist - SPRING_LEN) * SPRING_K;
        const nx = (dx / dist) * force, ny = (dy / dist) * force;
        fx[a] += nx; fy[a] += ny;
        fx[b] -= nx; fy[b] -= ny;
      }

      for (let i = 0; i < nodes.length; i++) {
        fx[i] += (W / 2 - nodes[i].x) * CENTER_PULL;
        fy[i] += (H / 2 - nodes[i].y) * CENTER_PULL;
        nodes[i].vx = (nodes[i].vx + fx[i]) * DAMPING;
        nodes[i].vy = (nodes[i].vy + fy[i]) * DAMPING;
        nodes[i].x += nodes[i].vx;
        nodes[i].y += nodes[i].vy;
        const margin = 50;
        if (nodes[i].x < margin) nodes[i].vx += 0.5;
        if (nodes[i].x > W - margin) nodes[i].vx -= 0.5;
        if (nodes[i].y < margin) nodes[i].vy += 0.5;
        if (nodes[i].y > H - margin) nodes[i].vy -= 0.5;
      }

      ctx.save();
      ctx.translate(cx, cy);
      ctx.scale(cam.scale, cam.scale);
      ctx.translate(-cam.x, -cam.y);

      for (const [a, b] of EDGES) {
        const na = nodes[a], nb = nodes[b];
        const dx = nb.x - na.x, dy = nb.y - na.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const alpha = Math.max(0, 0.35 - dist / 900);
        const grad = ctx.createLinearGradient(na.x, na.y, nb.x, nb.y);
        grad.addColorStop(0, `rgba(34,211,238,${alpha})`);
        grad.addColorStop(1, `rgba(124,90,246,${alpha})`);
        ctx.beginPath();
        ctx.moveTo(na.x, na.y);
        ctx.lineTo(nb.x, nb.y);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }

      for (const n of nodes) {
        const isSelected = sel?.id === n.id;
        const isMatch = anyMatch && n.label.toLowerCase().includes(q.toLowerCase());
        const isDimmed = anyMatch && !isMatch && !isSelected;
        ctx.globalAlpha = isDimmed ? 0.2 : 1;

        const glowR = n.size * (isMatch ? 6 : isSelected ? 5 : 4);
        const grd = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, glowR);
        grd.addColorStop(0, n.color + (isMatch ? "50" : "28"));
        grd.addColorStop(1, "transparent");
        ctx.beginPath();
        ctx.arc(n.x, n.y, glowR, 0, Math.PI * 2);
        ctx.fillStyle = grd;
        ctx.fill();

        if (isMatch || isSelected) {
          const pulse = 0.5 + 0.5 * Math.sin(t * 0.06);
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.size + 5 + pulse * 4, 0, Math.PI * 2);
          ctx.strokeStyle = n.color + "60";
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }

        ctx.beginPath();
        ctx.arc(n.x, n.y, n.size, 0, Math.PI * 2);
        ctx.fillStyle = n.color;
        ctx.fill();

        if (isSelected) {
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.size + 5, 0, Math.PI * 2);
          ctx.strokeStyle = n.color;
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        ctx.beginPath();
        ctx.arc(n.x - n.size * 0.28, n.y - n.size * 0.28, n.size * 0.38, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255,255,255,0.45)";
        ctx.fill();

        ctx.globalAlpha = 1;

        if ((isMatch || isSelected) && !isDimmed) {
          ctx.save();
          ctx.font = `500 11px 'DM Sans', sans-serif`;
          ctx.textAlign = "center";
          const tw = ctx.measureText(n.label).width;
          const pad = 6;
          ctx.fillStyle = "rgba(8,11,18,0.88)";
          ctx.beginPath();
          ctx.roundRect(n.x - tw / 2 - pad, n.y + n.size + 6, tw + pad * 2, 16, 4);
          ctx.fill();
          ctx.fillStyle = isMatch ? "#22d3ee" : "#e8ecf5";
          ctx.fillText(n.label, n.x, n.y + n.size + 17);
          ctx.restore();
        }
      }

      ctx.restore();
      rafRef.current = requestAnimationFrame(draw);
    }

    rafRef.current = requestAnimationFrame(draw);

    const onClick = (e: MouseEvent) => {
      const rect = canvas!.getBoundingClientRect();
      const cam = camRef.current;
      const cx = canvas!.offsetWidth / 2, cy = canvas!.offsetHeight / 2;
      const mx = (e.clientX - rect.left - cx) / cam.scale + cam.x;
      const my = (e.clientY - rect.top - cy) / cam.scale + cam.y;
      const hit = nodesRef.current.find((n) => Math.hypot(n.x - mx, n.y - my) < n.size + 10);
      if (hit) {
        setSelected(hit);
        targetCamRef.current = { x: hit.x, y: hit.y, scale: 1.6 };
      } else {
        setSelected(null);
        const W2 = canvas!.offsetWidth, H2 = canvas!.offsetHeight;
        targetCamRef.current = { x: W2 / 2, y: H2 / 2, scale: 1 };
      }
    };

    canvas.addEventListener("click", onClick);
    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("click", onClick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally empty — all mutable state accessed via refs

  const handleDeselect = () => {
    setSelected(null);
    const canvas = canvasRef.current;
    if (canvas) {
      targetCamRef.current = { x: canvas.offsetWidth / 2, y: canvas.offsetHeight / 2, scale: 1 };
    }
  };

  const matchCount = query ? nodesRef.current.filter((n) =>
    n.label.toLowerCase().includes(query.toLowerCase())
  ).length : 0;

  return (
    <div className="relative w-full h-full overflow-hidden">
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full cursor-crosshair" />

      {/* Search */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10">
        <div
          className="flex items-center gap-2 rounded-xl px-3 py-2"
          style={{
            background: "rgba(14,19,32,0.92)",
            border: `1px solid ${query ? "rgba(34,211,238,0.35)" : "rgba(255,255,255,0.08)"}`,
            backdropFilter: "blur(12px)",
            width: 260,
            transition: "border-color 0.2s",
          }}
        >
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none" style={{ color: query ? "#22d3ee" : "#3d4a63", flexShrink: 0 }}>
            <circle cx="5.5" cy="5.5" r="4" stroke="currentColor" strokeWidth="1.4" />
            <line x1="8.5" y1="8.5" x2="12" y2="12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          <input
            ref={searchRef}
            value={queryInput}
            onChange={(e) => { setQueryInput(e.target.value); setQueryBoth(e.target.value); }}
            placeholder="Search nodes… (press /)"
            className="flex-1 bg-transparent text-sm outline-none"
            style={{ color: "#e8ecf5" }}
          />
          {query ? (
            <button onClick={() => { setQueryBoth(""); setQueryInput(""); }} style={{ color: "#3d4a63" }}>
              <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
                <path d="M1 1l9 9M10 1L1 10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              </svg>
            </button>
          ) : (
            <span className="text-xs px-1.5 py-0.5 rounded font-mono shrink-0"
              style={{ background: "rgba(255,255,255,0.06)", color: "#3d4a63", fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }}>
              /
            </span>
          )}
        </div>
        {query && (
          <div className="text-center mt-1.5">
            <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: "rgba(34,211,238,0.1)", color: "#22d3ee" }}>
              {matchCount} match{matchCount !== 1 ? "es" : ""}
            </span>
          </div>
        )}
      </div>

      {/* Legend */}
      {showLegend && (
        <div className="absolute bottom-20 left-4 rounded-xl p-3 text-xs"
          style={{ background: "rgba(14,19,32,0.92)", border: "1px solid rgba(255,255,255,0.07)", backdropFilter: "blur(8px)" }}>
          <div className="font-mono mb-2" style={{ color: "#6b7a99", fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }}>
            node color = type
          </div>
          {(["document", "image", "sealed"] as const).map((t) => (
            <div key={t} className="flex items-center gap-2 mb-1 last:mb-0">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: COLOR_MAP[t] }} />
              <span style={{ color: "#9aa5bc" }}>{t}</span>
            </div>
          ))}
          <button onClick={() => setShowLegend(false)} className="mt-2 text-xs w-full text-center" style={{ color: "#3d4a63" }}>
            dismiss
          </button>
        </div>
      )}

      {/* Ask bar */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 rounded-xl px-3 py-2"
        style={{
          background: "rgba(14,19,32,0.9)",
          border: "1px solid rgba(255,255,255,0.1)",
          backdropFilter: "blur(12px)",
          width: "min(500px, calc(100% - 120px))",
        }}>
        <button className="text-xs px-2 py-1 rounded-md shrink-0 font-medium"
          style={{ background: "rgba(255,255,255,0.06)", color: "#6b7a99" }}>
          history
        </button>
        <input
          value={askText}
          onChange={(e) => setAskText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && askText.trim()) { onNavigate("chat"); setAskText(""); } }}
          placeholder="Ask about your documents…"
          className="flex-1 bg-transparent text-sm outline-none"
          style={{ color: "#e8ecf5" }}
        />
        <button
          onClick={() => { if (askText.trim()) { onNavigate("chat"); setAskText(""); } }}
          className="px-3 py-1 rounded-lg text-xs font-semibold shrink-0 transition-opacity"
          style={{ background: "#7c5af6", color: "#fff", opacity: askText.trim() ? 1 : 0.5 }}>
          Ask
        </button>
      </div>

      {/* Node detail panel */}
      {selected && (
        <div className="absolute top-4 right-4 rounded-xl p-4 w-52"
          style={{
            background: "rgba(14,19,32,0.96)",
            border: "1px solid rgba(255,255,255,0.09)",
            backdropFilter: "blur(12px)",
            animation: "slide-in-right 0.2s ease forwards",
          }}>
          <div className="flex items-start justify-between mb-3">
            <div>
              <div className="font-medium text-sm leading-tight mb-1" style={{ color: "#e8ecf5" }}>{selected.label}</div>
              <div className="text-xs flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: selected.color }} />
                <span className="capitalize" style={{ color: selected.color }}>{selected.type}</span>
              </div>
            </div>
            <button onClick={handleDeselect} style={{ color: "#3d4a63" }}>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </div>
          <div className="space-y-1.5">
            <button
              onClick={() => onNavigate("chat")}
              className="w-full text-left text-xs px-3 py-2 rounded-lg transition-colors"
              style={{ background: "rgba(255,255,255,0.05)", color: "#9aa5bc" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(124,90,246,0.12)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.05)")}
            >
              Chat about this
            </button>
            <button
              onClick={() => onNavigate("documents")}
              className="w-full text-left text-xs px-3 py-2 rounded-lg transition-colors"
              style={{ background: "rgba(255,255,255,0.05)", color: "#9aa5bc" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.08)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.05)")}
            >
              Open in Documents
            </button>
            <button
              onClick={handleDeselect}
              className="w-full text-left text-xs px-3 py-2 rounded-lg transition-colors"
              style={{ background: "transparent", color: "#3d4a63" }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "#6b7a99")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "#3d4a63")}
            >
              Zoom out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
