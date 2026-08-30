-- Stage 1.1 (revised) — the signed-URL direct-to-storage upload flow means
-- the PUT goes browser -> Supabase directly, bypassing services/api
-- entirely. So Supabase's own bucket-level config is the real enforcement
-- for both size and mime type, not just a client-side check or a FastAPI
-- check that never sees these bytes. Confirmed against current Supabase
-- docs: Free plan's global file size limit caps at 50MB, and a bucket
-- limit can't exceed that — we're at the ceiling, no headroom.

update storage.buckets
set
  file_size_limit = 52428800, -- 50MB in bytes
  allowed_mime_types = array['text/plain', 'application/pdf', 'image/jpeg', 'image/png', 'image/webp']
where id = 'originals';
