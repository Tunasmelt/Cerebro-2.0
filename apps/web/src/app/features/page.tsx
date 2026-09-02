import Link from "next/link";

import Logo from "@/components/Logo";
import Reveal from "@/components/Reveal";
import styles from "./features.module.css";

// Stage 4.7 — public marketing page, always viewable regardless of
// auth state (unlike "/", this one has no reason to redirect a signed-
// in visitor away).
export default function FeaturesPage() {
  return (
    <div className={styles.page}>
      <nav className={styles.navbar}>
        <div className={`${styles.container} ${styles.navbarInner}`}>
          <Link href="/" className={styles.navbarBrand}>
            <Logo size={22} />
          </Link>
          <div className={styles.navbarLinks}>
            <Link href="/signin">Sign in</Link>
            <Link href="/signup" className={styles.btnPrimary}>
              Try it
            </Link>
          </div>
        </div>
      </nav>

      <div className={`${styles.pageHead} ${styles.container}`}>
        <Reveal>
          <div className={styles.eyebrow}>Features</div>
          <h1>How Cerebro actually works.</h1>
        </Reveal>
      </div>

      <div className={styles.container}>
        <Reveal className={styles.row}>
          <div className={styles.rowVisual}>
            <svg viewBox="0 0 400 160" width="100%" height="160">
              <circle cx="200" cy="80" r="7" fill="#8B5CF6" />
              <circle cx="260" cy="50" r="4.5" fill="#A1A1AA" opacity="0.7" />
              <circle cx="310" cy="85" r="5" fill="#2DD4BF" />
              <line x1="200" y1="80" x2="260" y2="50" stroke="rgba(139,92,246,0.35)" strokeWidth="1.2" />
              <line x1="200" y1="80" x2="310" y2="85" stroke="rgba(139,92,246,0.35)" strokeWidth="1.2" />
            </svg>
          </div>
          <div className={styles.rowText}>
            <div className={styles.eyebrow}>01 · Ingest</div>
            <h2>One index for documents and images</h2>
            <p>
              Drop in PDFs, notes, and photos of whiteboards or printed
              pages — they all land in the same graph. Cerebro reads text
              and images alike, so a scanned diagram and a typed note can
              end up in the same retrieved cluster.
            </p>
          </div>
        </Reveal>

        <Reveal className={styles.row}>
          <div className={styles.rowText}>
            <div className={styles.eyebrow}>02 · Retrieval</div>
            <h2>Search finds it two ways, then merges</h2>
            <p>
              Every query runs as both a meaning-based vector search and a
              plain keyword search. The two result lists get merged into a
              single ranking, so an exact term match and a conceptually
              related note can both surface — whichever actually answers
              you.
            </p>
          </div>
          <div className={styles.rowVisual}>
            <div className={styles.lane} style={{ marginBottom: 16 }}>
              <span className={styles.laneLabel}>vector</span>
              <div className={styles.laneTrack}>
                <div className={styles.laneFill} style={{ width: "72%", background: "var(--accent-primary)" }} />
              </div>
            </div>
            <div className={styles.lane} style={{ marginBottom: 16 }}>
              <span className={styles.laneLabel}>full-text</span>
              <div className={styles.laneTrack}>
                <div className={styles.laneFill} style={{ width: "54%", background: "var(--accent-secondary)" }} />
              </div>
            </div>
            <div className={styles.lane}>
              <span className={styles.laneLabel}>ranked</span>
              <div className={styles.laneTrack}>
                <div className={styles.laneFill} style={{ width: "88%", background: "var(--text-primary)" }} />
              </div>
            </div>
          </div>
        </Reveal>

        <Reveal className={styles.row}>
          <div className={styles.rowVisual} style={{ minHeight: 280 }}>
            <svg viewBox="0 0 400 240" width="100%" height="240">
              <line x1="90" y1="70" x2="140" y2="100" stroke="rgba(244,244,245,0.1)" strokeWidth="1" />
              <circle cx="90" cy="70" r="5" fill="#A1A1AA" opacity="0.7" />
              <circle cx="140" cy="100" r="6" fill="#A1A1AA" opacity="0.8" />
              <circle cx="240" cy="150" r="8" fill="#8B5CF6" />
              <circle cx="290" cy="120" r="5" fill="#A78BFA" opacity="0.8" />
              <circle cx="320" cy="190" r="5" fill="#2DD4BF" />
            </svg>
          </div>
          <div className={styles.rowText}>
            <div className={styles.eyebrow}>03 · The graph</div>
            <h2>The whole vault, laid out by meaning</h2>
            <p>
              Documents that discuss similar ideas sit close together;
              unrelated ones drift apart. The clustering comes directly
              from embedding distance, so the shape of your vault is a
              rough map of what you&apos;ve actually been thinking about.
            </p>
          </div>
        </Reveal>

        <Reveal className={styles.row}>
          <div className={styles.rowText}>
            <div className={styles.eyebrow}>04 · Sealed files</div>
            <h2>Lock what matters, unlock only when needed</h2>
            <p>
              A sealed document is excluded from search and retrieval —
              even Cerebro&apos;s own chat can&apos;t cite it — until you
              unlock it with your passphrase. The passphrase itself is
              never stored.
            </p>
          </div>
          <div className={styles.rowVisual}>
            <svg viewBox="0 0 200 60" width="100%" height="60">
              <rect x="4" y="10" width="16" height="14" rx="3" fill="var(--accent-locked)" />
              <path d="M8 10V6a4 4 0 0 1 8 0v4" stroke="var(--accent-locked)" strokeWidth="1.6" fill="none" />
            </svg>
          </div>
        </Reveal>

        <Reveal className={styles.row}>
          <div className={styles.rowVisual}>
            <div className={styles.screenshot}>
              <div className={styles.screenshotBody}>
                Raft favors a strong single leader
                <span className={styles.cite}> [1]</span>, while Paxos
                allows multiple proposers to compete for a slot
                <span className={styles.cite}> [2]</span>.
              </div>
            </div>
          </div>
          <div className={styles.rowText}>
            <div className={styles.eyebrow}>05 · Traceability</div>
            <h2>Every claim traces back</h2>
            <p>
              Each sentence in an answer links to the exact chunk it came
              from. Click a citation and you&apos;re looking at the
              source, not a paraphrase of it.
            </p>
          </div>
        </Reveal>
      </div>

      <section className={styles.ctaBand}>
        <Reveal className={styles.container}>
          <h2>Start building your vault.</h2>
          <Link href="/signup" className={styles.btnPrimary}>
            Try it
          </Link>
        </Reveal>
      </section>
    </div>
  );
}
