"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Logo from "@/components/Logo";
import Reveal from "@/components/Reveal";
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

  if (checkingSession) return null;

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
            <Link href="/signup" className={styles.btnPrimary}>
              Try it
            </Link>
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
            <Link href="/signup" className={styles.btnPrimary}>
              Try it
            </Link>
          </Reveal>
          <Reveal delayMs={120}>
            <HeroGraph />
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
            <div className={styles.chips}>
              <span className={styles.chip}>[1] raft-paper.pdf</span>
              <span className={styles.chip}>[2] paxos-made-simple.pdf</span>
              <span className={styles.chip}>[3] note_2025-03-12.md</span>
            </div>
          </Reveal>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <Reveal>
            <div className={styles.eyebrow}>02</div>
            <h2 className={styles.sectionTitle}>Lock what matters</h2>
            <p className={styles.sectionSub}>
              Seal a note behind a passphrase. It stays sealed — even from
              Cerebro&apos;s own retrieval — until you unlock it again.
            </p>
          </Reveal>
          <div className={styles.lockGrid}>
            <Reveal delayMs={80} className={styles.lockCard}>
              <span className={styles.lockBadge}>Sealed</span>
              <div className={styles.lockFilename}>distributed-systems-notes.pdf</div>
              <div className={styles.lockMeta}>sealed · passphrase required</div>
            </Reveal>
            <Reveal delayMs={160}>
              <p className={styles.sectionSub} style={{ maxWidth: 460 }}>
                Sealed files are excluded from search and retrieval until
                unlocked with your passphrase. The passphrase itself is never
                stored, and no answer will ever cite a sealed node.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <div className={styles.features}>
            <Reveal delayMs={0} className={styles.feature}>
              <div className={styles.featureDot} style={{ background: "var(--accent-primary)", color: "var(--accent-primary)" }} />
              <h3>Multimodal search</h3>
              <p>Query across PDFs, images, and scans with the same plain-language search.</p>
            </Reveal>
            <Reveal delayMs={90} className={styles.feature}>
              <div className={styles.featureDot} style={{ background: "var(--accent-secondary)", color: "var(--accent-secondary)" }} />
              <h3>Real retrieval visualization</h3>
              <p>See the actual nodes and edges behind every answer, rendered live — not simulated for effect.</p>
            </Reveal>
            <Reveal delayMs={180} className={styles.feature}>
              <div className={styles.featureDot} style={{ background: "var(--accent-locked)", color: "var(--accent-locked)" }} />
              <h3>Passphrase-sealed files</h3>
              <p>Seal anything behind a passphrase. It stays sealed, even from retrieval, until you unlock it.</p>
            </Reveal>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.ctaBand}`}>
        <div className={styles.container}>
          <Reveal>
            <h2>Start building your vault.</h2>
            <Link href="/signup" className={styles.btnPrimary}>
              Try it
            </Link>
          </Reveal>
        </div>
      </section>

      <footer className={styles.footer}>
        <div className={styles.container}>
          <div className={styles.footerRow}>
            <Logo size={18} className={styles.footerBrand} />
            <div className={styles.footerLinks}>
              <Link href="/features">Features</Link>
              <Link href="/signin">Sign in</Link>
            </div>
          </div>
          <div className={styles.footerNote}>passphrase-gated locking, session-scoped.</div>
        </div>
      </footer>
    </div>
  );
}
