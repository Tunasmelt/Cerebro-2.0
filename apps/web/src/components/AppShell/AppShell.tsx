"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import Logo from "@/components/Logo";
import QuickCapture from "@/components/QuickCapture";
import { createClient } from "@/lib/supabase/client";
import styles from "./AppShell.module.css";

// Stage 4.7 — wraps every authenticated page (Brain, Documents, Kanban,
// Tasks, Settings, Playground) with the shared sidebar/topbar from
// Mockups/ui_kits/app-shell. No search box or ingest-status pill —
// both would be UI that claims to do something without a real feature
// behind it yet, which this project treats as a defect (citations,
// retrieval pulses, etc. are all real, never decorative).

const NAV_ITEMS = [
  { href: "/graph", label: "Brain" },
  { href: "/documents", label: "Documents" },
  { href: "/kanban", label: "Kanban" },
  { href: "/tasks", label: "Tasks" },
  { href: "/playground", label: "Playground" },
];

function initials(email: string | null): string {
  if (!email) return "?";
  return email.slice(0, 2).toUpperCase();
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
            >
              <span className={styles.navLabel}>{item.label}</span>
            </Link>
          ))}
        </div>

        <div className={styles.sidebarBottom}>
          <Link
            href="/settings"
            className={`${styles.navItem} ${pathname?.startsWith("/settings") ? styles.navItemActive : ""}`}
          >
            <span className={styles.navLabel}>Settings</span>
          </Link>
        </div>
      </div>

      <div className={styles.main}>
        <div className={styles.topbar}>
          <div className={styles.topbarRight}>
            <QuickCapture />
            <div className={styles.avatar} onClick={() => setMenuOpen((o) => !o)}>
              <span className={styles.avatarInner}>{initials(userEmail)}</span>
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
