"use client";

import Link from "next/link";
import { useState } from "react";

import Logo from "@/components/Logo";
import { createClient } from "@/lib/supabase/client";
import styles from "../auth.module.css";

export default function SignUpPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [checkEmail, setCheckEmail] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }

    setLoading(true);
    const supabase = createClient();
    const { error: signUpError } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/confirm`,
      },
    });
    setLoading(false);

    if (signUpError) {
      setError(signUpError.message);
      return;
    }
    setCheckEmail(true);
  }

  if (checkEmail) {
    return (
      <div className={styles.page}>
        <div className={styles.logoRow}>
          <Logo size={26} />
        </div>
        <div className={styles.card}>
          <h1 className={styles.title}>Check your email</h1>
          <p className={styles.info}>
            We sent a confirmation link to {email}. Click it to finish
            creating your account.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.logoRow}>
        <Logo size={26} />
      </div>
      <form className={styles.card} onSubmit={handleSubmit}>
        <h1 className={styles.title}>Create your account</h1>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={`${styles.input} ${error ? styles.inputError : ""}`}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={`${styles.input} ${error ? styles.inputError : ""}`}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="confirmPassword">
            Confirm password
          </label>
          <input
            id="confirmPassword"
            type="password"
            required
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className={`${styles.input} ${error ? styles.inputError : ""}`}
          />
        </div>

        {error && <p className={styles.errorMessage}>{error}</p>}

        <button type="submit" className={styles.button} disabled={loading}>
          {loading ? "Creating account…" : "Create account"}
        </button>

        <p className={styles.link}>
          Already have an account? <Link href="/signin">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
