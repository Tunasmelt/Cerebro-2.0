"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import styles from "../auth.module.css";

export default function AccountPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [probeResult, setProbeResult] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) {
        router.replace("/signin");
        return;
      }
      setEmail(session.user.email ?? null);
      setChecking(false);
    });
  }, [router]);

  async function runProbe() {
    setProbeResult("Calling services/api…");
    const response = await authedFetch("/api/probe");
    const body = await response.text();
    setProbeResult(`status=${response.status} body=${body}`);
  }

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/signin");
  }

  if (checking) return null;

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>Signed in</h1>
        <p className={styles.info}>{email}</p>

        <button className={styles.button} onClick={runProbe}>
          Call a protected API route
        </button>
        {probeResult && (
          <p className={styles.info} style={{ wordBreak: "break-all" }}>
            {probeResult}
          </p>
        )}

        <button className={styles.button} onClick={handleSignOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}
