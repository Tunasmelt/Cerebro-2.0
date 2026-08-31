-- Fixes the function_search_path_mutable security advisory on both
-- Stage 1.5 RPC functions. Must include `extensions`, not just `public`
-- — the halfvec <=> operator lives in the extensions schema (moved
-- there in Stage 0.2's own search_path fix), so pinning to public alone
-- breaks vector search with "operator does not exist" — caught live,
-- not assumed, when the first real RPC call failed after applying a
-- public-only search_path.
alter function match_chunks_vector(halfvec(1024), int) set search_path = public, extensions;
alter function match_chunks_fts(text, int) set search_path = public, extensions;
