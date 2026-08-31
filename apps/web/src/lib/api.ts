import { createClient } from "@/lib/supabase/client";

/**
 * Fetches one of this app's own /api/* proxy routes with the current
 * Supabase session's access token attached as a Bearer header — this is
 * the actual mechanism that makes "the session's JWT authenticates
 * requests to services/api" true, not just a claim (Stage 1.6).
 */
export async function authedFetch(path: string, init?: RequestInit) {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const headers = new Headers(init?.headers);
  if (session?.access_token) {
    headers.set("Authorization", `Bearer ${session.access_token}`);
  }

  return fetch(path, { ...init, headers });
}
