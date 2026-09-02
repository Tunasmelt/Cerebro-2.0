import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";

// Stage 4.7 — every authenticated page had its own copy of this exact
// session-check + redirect-to-signin effect (Stage 1.6 onward); pulled
// out once here so AppShell has a real email to render without a fifth
// copy of the same fetch.
export function useAuthedUser(): { checking: boolean; email: string | null } {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [email, setEmail] = useState<string | null>(null);

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

  return { checking, email };
}
