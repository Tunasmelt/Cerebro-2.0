-- Adds text/markdown to the originals bucket's allowed mime types.
-- 0004_originals_bucket_limits.sql is the real enforcement boundary for
-- uploads (the signed-URL flow means the PUT goes browser -> Supabase
-- directly, never through services/api) — ALLOWED_MIME_TYPES in
-- documents_storage.py is fast client-feedback only and was updated
-- alongside this migration, but without this the bucket itself would
-- still reject a .md upload with EntityTooLarge/mime-type errors.
update storage.buckets
set
  allowed_mime_types = array['text/plain', 'text/markdown', 'application/pdf', 'image/jpeg', 'image/png', 'image/webp']
where id = 'originals';
