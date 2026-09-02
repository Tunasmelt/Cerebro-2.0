"use client";

import type { CSSProperties, ReactNode } from "react";

import { useScrollReveal } from "@/lib/useScrollReveal";

/** Fades + slides an element in the first time it scrolls into view.
 * Inline-styled (not a CSS module class) so it stays a single drop-in
 * primitive usable from any page's own module without every page
 * needing to define its own reveal keyframes. `delayMs` staggers
 * siblings (feature cards, list rows) so they don't all pop at once. */
export default function Reveal({
  children,
  delayMs = 0,
  className,
  style,
}: {
  children: ReactNode;
  delayMs?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const { ref, revealed } = useScrollReveal<HTMLDivElement>();

  return (
    <div
      ref={ref}
      className={className}
      style={{
        ...style,
        opacity: revealed ? 1 : 0,
        transform: revealed ? "translateY(0)" : "translateY(16px)",
        transition: `opacity var(--duration-slow) var(--ease-soft) ${delayMs}ms, transform var(--duration-slow) var(--ease-soft) ${delayMs}ms`,
      }}
    >
      {children}
    </div>
  );
}
