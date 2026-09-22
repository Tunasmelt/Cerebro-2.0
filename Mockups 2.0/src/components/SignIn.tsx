import { useState } from "react";

interface Props {
  onSignIn: () => void;
  onBack: () => void;
}

export default function SignIn({ onSignIn, onBack }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = () => {
    if (!email.trim()) { setError("Email is required."); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setError("Enter a valid email address."); return; }
    if (password.length < 6) { setError("Password must be at least 6 characters."); return; }
    setError("");
    setLoading(true);
    setTimeout(() => { setLoading(false); onSignIn(); }, 900);
  };

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center relative"
      style={{ background: "#080b12", fontFamily: "'DM Sans', sans-serif" }}
    >
      <div className="absolute inset-0 pointer-events-none"
        style={{ background: "radial-gradient(ellipse 50% 40% at 50% 45%, rgba(124,90,246,0.07) 0%, transparent 70%)" }} />

      <button onClick={onBack} className="flex items-center gap-2 mb-10 relative z-10 transition-opacity"
        onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.7")}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
      >
        <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
          <circle cx="6" cy="11" r="3" fill="#7c5af6" />
          <circle cx="16" cy="6" r="2.5" fill="#22d3ee" />
          <circle cx="16" cy="16" r="2" fill="#7c5af6" opacity="0.7" />
          <line x1="9" y1="11" x2="13.5" y2="7" stroke="rgba(255,255,255,0.3)" strokeWidth="1" />
          <line x1="9" y1="11" x2="13.5" y2="15" stroke="rgba(255,255,255,0.3)" strokeWidth="1" />
        </svg>
        <span style={{ fontFamily: "'Outfit', sans-serif", fontWeight: 700, fontSize: 18, color: "#e8ecf5" }}>
          Cerebro
        </span>
      </button>

      <div className="relative z-10 w-full max-w-sm rounded-2xl p-8"
        style={{ background: "#0e1320", border: "1px solid rgba(255,255,255,0.08)", boxShadow: "0 24px 80px rgba(0,0,0,0.5)" }}
      >
        <h1 className="text-xl font-semibold mb-6"
          style={{ color: "#f0f2f7", fontFamily: "'Outfit', sans-serif", letterSpacing: "-0.01em" }}>
          Sign in
        </h1>

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "#6b7a99" }}>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setError(""); }}
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-all"
              style={{ background: "#141b2d", border: "1px solid rgba(255,255,255,0.08)", color: "#e8ecf5" }}
              placeholder="you@example.com"
              autoComplete="email"
              onFocus={(e) => { e.target.style.borderColor = "rgba(124,90,246,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(124,90,246,0.1)"; }}
              onBlur={(e) => { e.target.style.borderColor = "rgba(255,255,255,0.08)"; e.target.style.boxShadow = "none"; }}
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-medium" style={{ color: "#6b7a99" }}>Password</label>
              <button className="text-xs transition-colors" style={{ color: "#3d4a63" }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "#22d3ee")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "#3d4a63")}
              >
                Forgot password?
              </button>
            </div>
            <input
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setError(""); }}
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-all"
              style={{ background: "#141b2d", border: "1px solid rgba(255,255,255,0.08)", color: "#e8ecf5" }}
              placeholder="••••••••"
              autoComplete="current-password"
              onFocus={(e) => { e.target.style.borderColor = "rgba(124,90,246,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(124,90,246,0.1)"; }}
              onBlur={(e) => { e.target.style.borderColor = "rgba(255,255,255,0.08)"; e.target.style.boxShadow = "none"; }}
            />
          </div>

          {error && (
            <p className="text-xs px-3 py-2 rounded-lg" style={{ color: "#f43f5e", background: "rgba(244,63,94,0.08)" }}>
              {error}
            </p>
          )}

          <button
            onClick={handleSubmit}
            disabled={loading}
            className="w-full py-2.5 rounded-lg font-semibold text-sm mt-2 transition-all"
            style={{
              background: loading ? "rgba(124,90,246,0.5)" : "#7c5af6",
              color: "#fff",
              boxShadow: loading ? "none" : "0 0 24px rgba(124,90,246,0.3)",
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </div>

        <p className="mt-5 text-center text-xs" style={{ color: "#6b7a99" }}>
          Don't have an account?{" "}
          <button onClick={onSignIn} className="font-medium transition-colors" style={{ color: "#22d3ee" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "#67e8f9")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "#22d3ee")}
          >
            Sign up
          </button>
        </p>
      </div>
    </div>
  );
}
