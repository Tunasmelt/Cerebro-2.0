import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";

// Stage 4.7 — every authenticated page had its own copy of this exact
// session-check + redirect-to-signin effect (Stage 1.6 onward); pulled
// out once here so AppShell has a real email to render without a fifth
// copy of the same fetch.
//
// Profile pass — displayName/avatarUrl come from user_metadata
// (Settings' Account pane writes them via supabase.auth.updateUser,
// same field names). Subscribed to onAuthStateChange (not just a
// one-shot getSession on mount) specifically so a profile edit shows up
// in AppShell's avatar immediately — updateUser() fires a real
// USER_UPDATED auth event, this hook just needed to listen for it.
export function useAuthedUser(): {
  checking: boolean;
  email: string | null;
  displayName: string | null;
  avatarUrl: string | null;
} {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [email, setEmail] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);

  useEffect(() => {
    const supabase = createClient();

    function applySession(user: {
      email?: string | null;
      user_metadata?: { display_name?: string; avatar_url?: string };
    }) {
      setEmail(user.email ?? null);
      setDisplayName(user.user_metadata?.display_name || null);
      setAvatarUrl(user.user_metadata?.avatar_url || null);
    }

    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) {
        router.replace("/signin");
        return;
      }
      applySession(session.user);
      setChecking(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_OUT" || !session) {
        router.replace("/signin");
        return;
      }
      applySession(session.user);
    });

    return () => subscription.unsubscribe();
  }, [router]);

  return { checking, email, displayName, avatarUrl };
}
