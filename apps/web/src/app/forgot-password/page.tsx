"use client";

import Link from "next/link";
import { useState } from "react";

import Logo from "@/components/Logo";
import { createClient } from "@/lib/supabase/client";
import styles from "../auth.module.css";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    const supabase = createClient();
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/settings#security`,
    });
    setLoading(false);
    if (resetError) {
      setError(resetError.message);
      return;
    }
    setSent(true);
  }

  return (
    <div className={styles.page}>
      <div className={styles.logoRow}><Logo size={26} /></div>
      <form className={styles.card} onSubmit={handleSubmit}>
        <h1 className={styles.title}>{sent ? "Check your email" : "Reset your password"}</h1>
        {sent ? (
          <p className={styles.info}>If an account exists for {email}, a password-reset link is on its way.</p>
        ) : (
          <>
            <p className={styles.info}>Enter the email address associated with your Cerebro account.</p>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="email">Email</label>
              <input id="email" className={styles.input} type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
            </div>
            {error && <p className={styles.errorMessage}>{error}</p>}
            <button className={styles.button} type="submit" disabled={loading}>{loading ? "Sending…" : "Send reset link"}</button>
          </>
        )}
        <p className={styles.link}><Link href="/signin">Back to sign in</Link></p>
      </form>
    </div>
  );
}
