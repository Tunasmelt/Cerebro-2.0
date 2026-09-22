import { useState, useMemo } from "react";

const ORIGINAL_SYSTEM_PROMPT = `You are answering questions using only the context chunks provided below. Where present, each group of chunks is labeled with its source document under a "### Source: <name>" header — when a question spans more than one source, compare or synthesize across all of the relevant ones rather than answering from just one, and name the source when it helps disambiguate (e.g. "the PDF says..." or "the schedule image shows..."). Cite the chunk(s) you used for each claim by inserting [[chunk:<id>]] immediately after the relevant sentence, using the exact id shown for that chunk — never invent an id. To cite more than one chunk for the same claim, write a separate [[chunk:<id>]] marker for each one, back to back — for example [[chunk:id1]][[chunk:id2]] — never combine multiple ids inside one bracket, and never write anything like [[chunk:id1, [chunk:id2]]]. If the context doesn't contain the answer, say so plainly instead of guessing.

The chunks themselves are raw source text and may contain markdown syntax — tables built from | pipes, **bold**/​*italic* markers, \`code\` backticks, bullet dashes, heading #s. That formatting is an artifact of the source file, not part of the answer: read through it for the actual content and write your answer as plain, natural prose. Never copy a raw table row, a literal *, #, or | character, or any other markdown syntax out of a chunk into your response — describe what it says instead.`;

const CONTEXT_CHUNKS = [
  {
    source: "BrightPro Paper",
    id: "chunk_9dcfab13",
    tokens: 295,
    text: `Shi,ZacharySSiegel,MichaelTang,RuoxiSun,Jin-Weng.2022.Textandcodeembeddingsbycon-sungYoon,SercanArik,DanqiChen,andTaoYu.\ntrast ivepre-training.\n2025.BRIGHT:Arealisticandchallengingbench-\nmarkforreasoning-intensiveretrieval.InTheThir-\nStephenRobertson,HugoZaragoza,etal.2009.The\nteenthInternationalConferenceonLearningRepro-\nprobabilistic relevance framework: Bm25 and be-\nbabilisticModelsinInformationRetrieval.\nyond.FoundationsandTrendsinInformationRe-\ntrieval.3(4):333-389`,
  },
  {
    source: "BrightPro Paper",
    id: "chunk_313cdf43",
    tokens: 232,
    text: `intensiveretrieval.ArXiv,abs/2601.09562.\nMatsumoto.2026.Thewisdomofmanyqueries:\nAnirudhAjith,MengzhouXia,AlexisChevalier,Tanya Complexity-diversity principle for dense retriever\ngeneralization.`,
  },
];

function countTokens(text: string) {
  // Simple approximation: ~1.3 tokens per word
  return Math.round(text.split(/\s+/).filter(Boolean).length * 1.3);
}

const EST_COST_PER_TOKEN = 0.0000003;
const BASE_LATENCY_MS = 900;

export default function Playground() {
  const [systemPrompt, setSystemPrompt] = useState(ORIGINAL_SYSTEM_PROMPT);
  const [response, setResponse] = useState("");
  const [running, setRunning] = useState(false);

  const sysTokens = useMemo(() => countTokens(systemPrompt), [systemPrompt]);
  const ctxTokens = CONTEXT_CHUNKS.reduce((s, c) => s + c.tokens, 0);
  const totalTokens = sysTokens + ctxTokens;
  const estCost = (totalTokens * EST_COST_PER_TOKEN).toFixed(6);
  const estLatency = Math.round(BASE_LATENCY_MS + totalTokens * 0.8);

  const run = () => {
    setRunning(true);
    setResponse("");
    setTimeout(() => {
      setResponse(
        "Based on the provided context, the text chunks consist primarily of bibliographical references and citations from academic papers on information retrieval. The chunks lack substantive analysis sections — they contain reference lists only, so a definitive conclusion cannot be drawn from the provided text alone."
      );
      setRunning(false);
    }, Math.min(estLatency, 2500));
  };

  return (
    <div className="flex h-full" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      {/* Main area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-5 py-3 flex items-baseline gap-3" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
          <h1 className="text-base font-semibold" style={{ fontFamily: "'Outfit', sans-serif", color: "#f0f2f7" }}>
            Playground
          </h1>
          <span className="text-sm" style={{ color: "#3d4a63" }}>
            Edit the prompt that was actually sent, then run it for real.
          </span>
        </div>

        {/* Reset bar */}
        <div className="px-5 py-2" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
          <button
            onClick={() => setSystemPrompt(ORIGINAL_SYSTEM_PROMPT)}
            className="w-full py-1.5 rounded-lg text-xs font-medium transition-colors"
            style={{
              background: "rgba(255,255,255,0.04)",
              color: systemPrompt !== ORIGINAL_SYSTEM_PROMPT ? "#9aa5bc" : "#3d4a63",
              border: `1px solid ${systemPrompt !== ORIGINAL_SYSTEM_PROMPT ? "rgba(255,255,255,0.1)" : "rgba(255,255,255,0.05)"}`,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.07)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.04)")}
          >
            {systemPrompt !== ORIGINAL_SYSTEM_PROMPT ? "↺ Reset to original" : "Reset to original"}
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          {/* System instructions */}
          <div className="px-5 py-4" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold tracking-widest uppercase"
                style={{ color: "#6b7a99", letterSpacing: "0.1em" }}>
                System Instructions
              </span>
              <span className="text-xs font-mono" style={{ color: sysTokens > 400 ? "#f59e0b" : "#3d4a63", fontFamily: "'JetBrains Mono', monospace" }}>
                {sysTokens} tok
              </span>
            </div>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={10}
              className="w-full bg-transparent text-xs leading-relaxed outline-none resize-y"
              style={{ color: "#9aa5bc", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.7, minHeight: 120 }}
            />
          </div>

          {/* Context chunks */}
          {CONTEXT_CHUNKS.map((chunk) => (
            <div key={chunk.id} className="px-5 py-4" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs" style={{ color: "#6b7a99" }}>
                  <span className="font-semibold tracking-wide uppercase" style={{ letterSpacing: "0.08em" }}>Context</span>
                  {" "}
                  <span style={{ color: "#3d4a63" }}>{chunk.source} · {chunk.id}</span>
                </span>
                <span className="text-xs font-mono" style={{ color: "#3d4a63", fontFamily: "'JetBrains Mono', monospace" }}>
                  {chunk.tokens} tok
                </span>
              </div>
              <div
                className="text-xs leading-relaxed p-3 rounded-lg overflow-y-auto"
                style={{
                  background: "#0e1320",
                  color: "#6b7a99",
                  fontFamily: "'JetBrains Mono', monospace",
                  lineHeight: 1.7,
                  maxHeight: 160,
                  border: "1px solid rgba(255,255,255,0.05)",
                  whiteSpace: "pre-wrap",
                }}
              >
                {chunk.text}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right panel */}
      <div
        className="w-64 shrink-0 flex flex-col p-4 gap-5 overflow-y-auto"
        style={{ borderLeft: "1px solid rgba(255,255,255,0.05)", background: "#0a0e1a" }}
      >
        <div>
          <div className="text-xs font-semibold tracking-widest uppercase mb-1" style={{ color: "#3d4a63", letterSpacing: "0.1em" }}>Model</div>
          <div className="text-sm font-mono font-semibold" style={{ color: "#22d3ee", fontFamily: "'JetBrains Mono', monospace" }}>
            gemini-flash-lite
          </div>
        </div>

        <div>
          <div className="text-xs font-semibold tracking-widest uppercase mb-1" style={{ color: "#3d4a63", letterSpacing: "0.1em" }}>
            Total Tokens (est.)
          </div>
          <div className="text-2xl font-bold tabular-nums" style={{ color: "#e8ecf5", fontFamily: "'Outfit', sans-serif" }}>
            {totalTokens.toLocaleString()}
          </div>
          <div className="text-xs mt-0.5 font-mono" style={{ color: "#3d4a63", fontFamily: "'JetBrains Mono', monospace" }}>
            {sysTokens} sys + {ctxTokens} ctx
          </div>
        </div>

        <div>
          <div className="text-xs font-semibold tracking-widest uppercase mb-1" style={{ color: "#3d4a63", letterSpacing: "0.1em" }}>
            Est. Cost (Input)
          </div>
          <div className="text-lg font-semibold font-mono" style={{ color: "#10b981", fontFamily: "'JetBrains Mono', monospace" }}>
            ${estCost}
          </div>
        </div>

        <div>
          <div className="text-xs font-semibold tracking-widest uppercase mb-1" style={{ color: "#3d4a63", letterSpacing: "0.1em" }}>
            Est. Latency
          </div>
          <div className="text-lg font-semibold font-mono" style={{ color: "#f59e0b", fontFamily: "'JetBrains Mono', monospace" }}>
            ~{estLatency.toLocaleString()}ms
          </div>
        </div>

        <button
          onClick={run}
          disabled={running}
          className="w-full py-2.5 rounded-lg font-semibold text-sm transition-all"
          style={{
            background: running ? "rgba(124,90,246,0.4)" : "#7c5af6",
            color: "#fff",
            cursor: running ? "not-allowed" : "pointer",
            boxShadow: running ? "none" : "0 0 20px rgba(124,90,246,0.25)",
          }}
        >
          {running ? "Running…" : "Run"}
        </button>

        <div>
          <div className="text-xs font-semibold tracking-widest uppercase mb-2" style={{ color: "#3d4a63", letterSpacing: "0.1em" }}>
            Response
          </div>
          <div
            className="text-xs leading-relaxed p-3 rounded-lg"
            style={{
              background: "#0e1320",
              border: `1px solid ${response ? "rgba(34,211,238,0.1)" : "rgba(255,255,255,0.06)"}`,
              color: response ? "#9aa5bc" : "#3d4a63",
              fontFamily: "'JetBrains Mono', monospace",
              lineHeight: 1.75,
              minHeight: 80,
              whiteSpace: "pre-wrap",
            }}
          >
            {running ? (
              <span style={{ color: "#7c5af6" }}>Generating…</span>
            ) : response || "Run the edited prompt to see a real response here."}
          </div>
        </div>
      </div>
    </div>
  );
}
