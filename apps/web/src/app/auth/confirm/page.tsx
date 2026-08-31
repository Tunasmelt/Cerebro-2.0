"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";
import styles from "../../auth.module.css";

// Default Supabase "Confirm signup" email template points here via
// emailRedirectTo (see signup/page.tsx). @supabase/ssr's browser client
// defaults to the PKCE flow, so the link lands with a `?code=` param —
// no custom email template needed, unlike the token_hash/verifyOtp flow.
export default function ConfirmPage() {
  return (
    <Suspense fallback={null}>
      <ConfirmInner />
    </Suspense>
  );
}

function ConfirmInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      router.replace("/signin?error=confirmation_failed");
      return;
    }

    const supabase = createClient();
    supabase.auth.exchangeCodeForSession(code).then(({ error: exchangeError }) => {
      if (exchangeError) {
        setError(exchangeError.message);
        return;
      }
      router.replace("/account");
    });
  }, [router, searchParams]);

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>
          {error ? "Confirmation failed" : "Confirming…"}
        </h1>
        {error && <p className={styles.errorMessage}>{error}</p>}
      </div>
    </div>
  );
}
