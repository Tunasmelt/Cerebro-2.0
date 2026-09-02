"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// Stage 4.7 — /settings supersedes the old /account probe placeholder
// (Stage 0.5's "call a protected route" test page). Kept as a redirect,
// not deleted outright, since sign-in/email-confirm both used to land
// here — both now go straight to /graph, but an old bookmark or link
// shouldn't 404.
export default function AccountRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/settings");
  }, [router]);

  return null;
}
