import { useEffect, useRef, useState } from "react";

/** True from the moment the ref'd element first scrolls into view —
 * used to add a "revealed" class that CSS transitions from an
 * opacity:0/translateY(...) start state. Fires once (unobserves after
 * the first intersection) rather than toggling on every scroll past
 * the threshold, so re-scrolling up and down doesn't replay it. */
export function useScrollReveal<T extends HTMLElement>(threshold = 0.15) {
  const ref = useRef<T | null>(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setRevealed(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setRevealed(true);
          observer.unobserve(el);
        }
      },
      { threshold }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold]);

  return { ref, revealed };
}
