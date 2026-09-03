"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Logo from "@/components/Logo";
import QuickCapture from "@/components/QuickCapture";
import { createClient } from "@/lib/supabase/client";
import { useAuthedUser } from "@/lib/useAuthedUser";
import styles from "./AppShell.module.css";

// Stage 4.7 — wraps every authenticated page (Brain, Documents, Kanban,
// Tasks, Settings, Playground) with the shared sidebar/topbar from
// Mockups/ui_kits/app-shell. No search box or ingest-status pill —
// both would be UI that claims to do something without a real feature
// behind it yet, which this project treats as a defect (citations,
// retrieval pulses, etc. are all real, never decorative).

// Icons matching Mockups/ui_kits/app-shell/index.html exactly — the
// mockup always had real per-item icons; AppShell only ever rendered
// the text label, so collapsing the sidebar (which hides labels, see
// .sidebarCollapsed .navLabel below) left every nav item with nothing
// visible or clickable at all. currentColor so hover/active state
// (which recolors the whole .navItem) recolors the icon too.
const NAV_ICONS: Record<string, React.ReactNode> = {
  Brain: (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none">
      <circle cx="8.5" cy="8.5" r="2.2" fill="currentColor" />
      <circle cx="3.5" cy="4.5" r="1.3" fill="currentColor" opacity="0.6" />
      <circle cx="13.5" cy="5" r="1.3" fill="currentColor" opacity="0.6" />
      <circle cx="4" cy="13" r="1.3" fill="currentColor" opacity="0.6" />
      <circle cx="13" cy="12.5" r="1.3" fill="currentColor" opacity="0.6" />
      <path
        d="M8.5 8.5L3.5 4.5M8.5 8.5L13.5 5M8.5 8.5L4 13M8.5 8.5L13 12.5"
        stroke="currentColor"
        strokeWidth="0.8"
        opacity="0.4"
      />
    </svg>
  ),
  Documents: (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none">
      <rect x="3.5" y="2.5" width="10" height="12" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M6 6.5H11M6 9H11M6 11.5H9" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  ),
  Chat: (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none">
      <path
        d="M3 3.5H14V11H8.5L5 13.5V11H3V3.5Z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  ),
  Kanban: (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none">
      <rect x="2.5" y="3" width="12" height="11" rx="1.3" stroke="currentColor" strokeWidth="1.2" />
      <path d="M6.3 3V14M10.7 3V14" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  Tasks: (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none">
      <rect x="3.5" y="3.5" width="3" height="3" rx="0.6" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="M8.5 5H14M3.5 10.5H6.5V13.5H3.5V10.5ZM8.5 12H14"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  ),
  Playground: (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none">
      <path d="M5 3.5L13 8.5L5 13.5V3.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  ),
  Settings: (
    <svg width="17" height="17" viewBox="0 0 17 17" fill="none">
      <circle cx="8.5" cy="8.5" r="2" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="M8.5 3V4.5M8.5 12.5V14M14 8.5H12.5M4.5 8.5H3M12.2 4.8L11.2 5.8M5.8 11.2L4.8 12.2M12.2 12.2L11.2 11.2M5.8 5.8L4.8 4.8"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  ),
};

const NAV_ITEMS = [
  { href: "/graph", label: "Brain" },
  { href: "/documents", label: "Documents" },
  { href: "/chat", label: "Chat" },
  { href: "/kanban", label: "Kanban" },
  { href: "/tasks", label: "Tasks" },
  { href: "/playground", label: "Playground" },
];

function initials(name: string | null): string {
  if (!name) return "?";
  return name.slice(0, 2).toUpperCase();
}

export default function AppShell({
  children,
  userEmail,
}: {
  children: React.ReactNode;
  userEmail: string | null;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  // Profile pass — AppShell reads its own displayName/avatarUrl rather
  // than threading two more props through every page that mounts it
  // (every page already independently calls useAuthedUser for its own
  // `checking`/`userEmail`); this is the same session, just read twice,
  // not a second source of truth.
  const { displayName, avatarUrl } = useAuthedUser();
  const avatarLabel = displayName || userEmail;
  const [avatarImgFailed, setAvatarImgFailed] = useState(false);
  useEffect(() => setAvatarImgFailed(false), [avatarUrl]);

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/signin");
  }

  return (
    <div className={styles.shell}>
      <div className={`${styles.sidebar} ${collapsed ? styles.sidebarCollapsed : ""}`}>
        <div className={styles.sidebarTop}>
          <span className={styles.brandMark} onClick={() => router.push("/graph")}>
            <Logo size={collapsed ? 20 : 20} wordmark={!collapsed} />
          </span>
          <button
            className={`${styles.collapseBtn} ${collapsed ? styles.collapseBtnFlipped : ""}`}
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            ‹
          </button>
        </div>

        <div className={styles.navGroup}>
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`${styles.navItem} ${pathname?.startsWith(item.href) ? styles.navItemActive : ""}`}
              title={collapsed ? item.label : undefined}
            >
              {NAV_ICONS[item.label]}
              <span className={styles.navLabel}>{item.label}</span>
            </Link>
          ))}
        </div>

        <div className={styles.sidebarBottom}>
          <Link
            href="/settings"
            className={`${styles.navItem} ${pathname?.startsWith("/settings") ? styles.navItemActive : ""}`}
            title={collapsed ? "Settings" : undefined}
          >
            {NAV_ICONS.Settings}
            <span className={styles.navLabel}>Settings</span>
          </Link>
        </div>
      </div>

      <div className={styles.main}>
        <div className={styles.topbar}>
          <div className={styles.topbarRight}>
            <QuickCapture />
            <div className={styles.avatar} onClick={() => setMenuOpen((o) => !o)}>
              {avatarUrl && !avatarImgFailed ? (
                // eslint-disable-next-line @next/next/no-img-element -- user-pasted external URL, not a local/optimizable asset.
                <img
                  src={avatarUrl}
                  alt=""
                  className={styles.avatarImg}
                  onError={() => setAvatarImgFailed(true)}
                />
              ) : (
                <span className={styles.avatarInner}>{initials(avatarLabel)}</span>
              )}
              {menuOpen && (
                <div className={styles.avatarMenu}>
                  <button
                    className={styles.avatarMenuItem}
                    onClick={() => router.push("/settings")}
                  >
                    Settings
                  </button>
                  <button className={styles.avatarMenuItem} onClick={handleSignOut}>
                    Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className={styles.content} key={pathname}>
          {children}
        </div>
      </div>
    </div>
  );
}
