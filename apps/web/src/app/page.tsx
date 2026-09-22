"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Logo from "@/components/Logo";
import Reveal from "@/components/Reveal";
import RouteLoading from "@/components/RouteLoading";
import { createClient } from "@/lib/supabase/client";
import styles from "./page.module.css";

// Three.js touches the DOM/canvas directly, so it's loaded client-only
// and only on this page — no SSR cost, no bundle weight on any
// authenticated page that never renders it.
const HeroGraph = dynamic(() => import("./HeroGraph"), { ssr: false });

// Stage 4.7 — the real marketing landing page, replacing create-next-
// app's default boilerplate that was still live at "/" until now. A
// signed-in visitor is sent straight to the real product instead of
// being shown a pitch for something they already have.
//
// Post-4.7 design pass: adds the top navbar and logo that were both
// missing (every other page already had a nav via AppShell; this one
// didn't), scroll-triggered reveal animation on every section instead
// of everything being visible instantly, and the three.js ambient node
// graph replacing the static SVG dots.
export default function LandingPage() {
  const router = useRouter();
  const [checkingSession, setCheckingSession] = useState(true);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        router.replace("/graph");
        return;
      }
      setCheckingSession(false);
    });
  }, [router]);

  useEffect(() => {
    function onScroll() {
      setScrolled(window.scrollY > 8);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  if (checkingSession) return <RouteLoading />;

  return (
    <div className={styles.page}>
      <nav className={`${styles.navbar} ${scrolled ? styles.navbarScrolled : ""}`}>
        <div className={`${styles.container} ${styles.navbarInner}`}>
          <Link href="/" className={styles.navbarBrand}>
            <Logo size={22} />
          </Link>
          <div className={styles.navbarLinks}>
            <Link href="/features">Features</Link>
            <Link href="/signin">Sign in</Link>
            <Link href="/signup" className={styles.btnPrimary}>Try it</Link>
          </div>
        </div>
      </nav>

      <section className={styles.hero}>
        <div className={`${styles.container} ${styles.heroGrid}`}>
          <Reveal>
            <div className={styles.eyebrow}>Personal knowledge vault</div>
            <h1>
              Your documents,
              <br />
              as a <em>graph</em> you
              <br />
              can query.
            </h1>
            <p className={styles.heroSub}>
              Ask a question in plain language. Cerebro retrieves the exact
              nodes it used to answer — not a black box, not a decorative
              animation.
            </p>
            <div className={styles.heroActions}>
              <Link href="/signup" className={styles.btnPrimary}>Try it free</Link>
              <Link href="/signin" className={styles.btnSecondary}>Sign in</Link>
            </div>
          </Reveal>
          <Reveal delayMs={120}>
            <div className={styles.graphFrame}><HeroGraph /></div>
          </Reveal>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <Reveal>
            <div className={styles.eyebrow}>01</div>
            <h2 className={styles.sectionTitle}>Ask it anything you&apos;ve stored</h2>
            <p className={styles.sectionSub}>
              Every answer is grounded in nodes from your own vault, with
              citations back to source.
            </p>
          </Reveal>
          <Reveal delayMs={100} className={styles.chatCard}>
            <div className={`${styles.bubble} ${styles.bubbleQuery}`}>
              What did I read about consensus algorithms last spring?
            </div>
            <div className={`${styles.bubble} ${styles.bubbleAnswer}`}>
              You went through three papers on Raft and Paxos between March
              and April<span className={styles.cite}> [1][2]</span>, and
              your own notes flag Raft as easier to reason about for small
              clusters<span className={styles.cite}> [3]</span>.
            </div>
          </Reveal>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <Reveal className={styles.featureIntro}>
            <div className={styles.featureIndex}>FEATURES</div>
            <h2 className={styles.sectionTitle}>How Cerebro actually works.</h2>
          </Reveal>
          <div className={styles.featureRows}>
            <Reveal className={styles.featureRow}>
              <div className={styles.featureVisual}>
                <svg className={styles.miniGraph} viewBox="0 0 170 100" aria-hidden="true">
                  <line x1="35" y1="55" x2="100" y2="30" stroke="var(--border-strong)" />
                  <line x1="100" y1="30" x2="138" y2="68" stroke="var(--border-strong)" />
                  <circle cx="35" cy="55" r="9" fill="var(--accent-primary)" />
                  <circle cx="100" cy="30" r="7" fill="var(--accent-secondary)" />
                  <circle cx="138" cy="68" r="8" fill="var(--accent-primary)" opacity=".75" />
                </svg>
              </div>
              <div className={styles.featureCopy}>
                <div className={styles.featureIndex}>01 · INGEST</div>
                <h3>One index for documents and images</h3>
                <p>Drop in PDFs, notes, and photos of whiteboards or printed pages — they all land in the same graph. Cerebro reads text and images alike, so a scanned diagram and a typed note can end up in the same retrieved cluster.</p>
              </div>
            </Reveal>
            <Reveal className={`${styles.featureRow} ${styles.featureRowReverse}`}>
              <div className={styles.featureVisual}>
                <div className={styles.ranker}>
                  {[["vector","72%","var(--accent-primary)"],["full-text","55%","var(--accent-secondary)"],["ranked","86%","var(--text-primary)"]].map(([label,width,color]) => (
                    <div className={styles.rankRow} key={label}><span>{label}</span><div className={styles.rankTrack}><div className={styles.rankFill} style={{ width, background: color }} /></div></div>
                  ))}
                </div>
              </div>
              <div className={styles.featureCopy}>
                <div className={styles.featureIndex}>02 · RETRIEVAL</div>
                <h3>Search finds it two ways, then merges</h3>
                <p>Every query runs as both a meaning-based vector search and a plain keyword search. The two result lists get merged into a single ranking, so exact terms and conceptually related notes can both surface.</p>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.ctaBand}`}>
        <div className={styles.container}>
          <Reveal>
            <h2>Your knowledge, finally queryable.</h2>
            <p>Connect your documents, notes, and images. Start asking questions in seconds.</p>
            <Link href="/signup" className={styles.btnPrimary}>
              Get started free
            </Link>
          </Reveal>
        </div>
      </section>

      <footer className={styles.footer}>
        <div className={styles.container}>
          <div className={styles.footerRow}>
            <Logo size={18} className={styles.footerBrand} />
            <span>© 2026 Cerebro. Personal Knowledge Vault.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
