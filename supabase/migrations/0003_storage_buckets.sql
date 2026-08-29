-- Stage 0.3 — storage buckets: originals (untouched uploads) and indexed
-- (normalized files retrieval reads). Genuinely separate buckets, each with
-- its own RLS policies — never merge them (see architecture-and-security.md
-- §1).
--
-- Path convention (undocumented in the architecture doc, agreed explicitly
-- before this migration): {user_id}/{document_id}/original.{ext} in
-- originals, {user_id}/{document_id}/indexed.{ext} in indexed. This lets
-- every policy be a one-line prefix check — storage.objects has no
-- document_id column to join through, so a path-prefix convention is the
-- only practical way to scope storage RLS to a user.

insert into storage.buckets (id, name, public)
values
  ('originals', 'originals', false),
  ('indexed', 'indexed', false)
on conflict (id) do nothing;

-- originals ---------------------------------------------------------------

create policy originals_select_own on storage.objects
  for select using (
    bucket_id = 'originals'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy originals_insert_own on storage.objects
  for insert with check (
    bucket_id = 'originals'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy originals_update_own on storage.objects
  for update using (
    bucket_id = 'originals'
    and (storage.foldername(name))[1] = auth.uid()::text
  ) with check (
    bucket_id = 'originals'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy originals_delete_own on storage.objects
  for delete using (
    bucket_id = 'originals'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- indexed -------------------------------------------------------------------

create policy indexed_select_own on storage.objects
  for select using (
    bucket_id = 'indexed'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy indexed_insert_own on storage.objects
  for insert with check (
    bucket_id = 'indexed'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy indexed_update_own on storage.objects
  for update using (
    bucket_id = 'indexed'
    and (storage.foldername(name))[1] = auth.uid()::text
  ) with check (
    bucket_id = 'indexed'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy indexed_delete_own on storage.objects
  for delete using (
    bucket_id = 'indexed'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
