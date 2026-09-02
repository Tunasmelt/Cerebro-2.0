// The product's first real logo — previously every page just spelled
// out "Cerebro" as plain text (AppShell's sidebar brand mark, the
// landing footer, auth pages — none of it a mark). The glyph is three
// linked nodes forming the same node/edge language the brain graph
// itself uses (violet primary node, two teal satellites), not an
// arbitrary icon — so the mark reads as literally what the product does
// before a visitor ever reaches the graph page.
export function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <line x1="12" y1="12" x2="5" y2="6" stroke="var(--accent-secondary)" strokeWidth="1.4" strokeLinecap="round" />
      <line x1="12" y1="12" x2="19" y2="6" stroke="var(--accent-secondary)" strokeWidth="1.4" strokeLinecap="round" />
      <line x1="12" y1="12" x2="6" y2="19" stroke="var(--accent-secondary)" strokeWidth="1.4" strokeLinecap="round" opacity="0.6" />
      <circle cx="5" cy="6" r="2.2" fill="var(--accent-secondary)" opacity="0.85" />
      <circle cx="19" cy="6" r="2.2" fill="var(--accent-secondary)" opacity="0.85" />
      <circle cx="6" cy="19" r="1.8" fill="var(--accent-secondary)" opacity="0.55" />
      <circle cx="12" cy="12" r="3.4" fill="var(--accent-primary)" />
    </svg>
  );
}

export default function Logo({
  size = 22,
  wordmark = true,
  className,
}: {
  size?: number;
  wordmark?: boolean;
  className?: string;
}) {
  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}
    >
      <LogoMark size={size} />
      {wordmark && (
        <span
          style={{
            fontFamily: "var(--font-ui)",
            fontWeight: "var(--weight-semibold)" as unknown as number,
            fontSize: size * 0.8,
            color: "var(--text-primary)",
            letterSpacing: "-0.01em",
          }}
        >
          Cerebro
        </span>
      )}
    </span>
  );
}
