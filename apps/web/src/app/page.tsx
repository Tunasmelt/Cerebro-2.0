"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";
import styles from "./page.module.css";

// Stage 4.7 — the real marketing landing page, replacing create-next-
// app's default boilerplate that was still live at "/" until now. A
// signed-in visitor is sent straight to the real product instead of
// being shown a pitch for something they already have.
export default function LandingPage() {
  const router = useRouter();
  const [checkingSession, setCheckingSession] = useState(true);

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

  if (checkingSession) return null;

  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <div className={`${styles.container} ${styles.heroGrid}`}>
          <div>
            <div className={styles.eyebrow}>Personal knowledge vault</div>
            <h1>
              Your documents,
              <br />
              as a graph you
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
          </div>
          <div>
            <svg viewBox="0 0 560 440" width="100%" height="100%">
              <circle cx="220" cy="220" r="30" fill="rgba(139,92,246,0.10)" />
              <circle cx="80" cy="60" r="4" fill="#A1A1AA" opacity="0.7" />
              <circle cx="260" cy="110" r="6" fill="#2DD4BF" />
              <circle cx="380" cy="320" r="5.5" fill="#2DD4BF" opacity="0.9" />
              <circle cx="220" cy="220" r="9" fill="#8B5CF6" />
            </svg>
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <div className={styles.eyebrow}>01</div>
          <h2 className={styles.sectionTitle}>Ask it anything you&apos;ve stored</h2>
          <p className={styles.sectionSub}>
            Every answer is grounded in nodes from your own vault, with
            citations back to source.
          </p>
          <div className={styles.chatCard}>
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
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <div className={styles.eyebrow}>02</div>
          <h2 className={styles.sectionTitle}>Lock what matters</h2>
          <p className={styles.sectionSub}>
            Seal a note behind a passphrase. It stays sealed — even from
            Cerebro&apos;s own retrieval — until you unlock it again.
          </p>
          <div className={styles.lockGrid}>
            <div className={styles.lockCard}>
              <span className={styles.lockBadge}>Sealed</span>
              <div className={styles.lockFilename}>distributed-systems-notes.pdf</div>
              <div className={styles.lockMeta}>sealed · passphrase required</div>
            </div>
            <p className={styles.sectionSub} style={{ maxWidth: 460 }}>
              Sealed files are excluded from search and retrieval until
              unlocked with your passphrase. The passphrase itself is never
              stored, and no answer will ever cite a sealed node.
            </p>
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.container}>
          <div className={styles.features}>
            <div className={styles.feature}>
              <div className={styles.featureDot} style={{ background: "var(--accent-primary)" }} />
              <h3>Multimodal search</h3>
              <p>Query across PDFs, images, and scans with the same plain-language search.</p>
            </div>
            <div className={styles.feature}>
              <div className={styles.featureDot} style={{ background: "var(--accent-secondary)" }} />
              <h3>Real retrieval visualization</h3>
              <p>See the actual nodes and edges behind every answer, rendered live — not simulated for effect.</p>
            </div>
            <div className={styles.feature}>
              <div className={styles.featureDot} style={{ background: "var(--accent-locked)" }} />
              <h3>Passphrase-sealed files</h3>
              <p>Seal anything behind a passphrase. It stays sealed, even from retrieval, until you unlock it.</p>
            </div>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.ctaBand}`}>
        <div className={styles.container}>
          <h2>Start building your vault.</h2>
          <Link href="/signup" className={styles.btnPrimary}>
            Try it
          </Link>
        </div>
      </section>

      <footer className={styles.footer}>
        <div className={styles.container}>
          <div className={styles.footerRow}>
            <div className={styles.footerBrand}>Cerebro</div>
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
