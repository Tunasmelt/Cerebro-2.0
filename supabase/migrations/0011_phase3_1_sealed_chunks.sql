-- Stage 3.1 — sealed_chunks, fully isolated from chunks. CLAUDE.md's
-- non-negotiable constraint: "Never let a sealed document's chunk text
-- enter the retrieval index in plaintext, and never let embedding
-- vectors for sealed content exist outside the isolated sealed_chunks
-- table." This table has no embedding column at all — sealed content is
-- never vectorized outside an active unlock (Stage 3.2+ handles that
-- client-side, per-request, never persisted here.)
--
-- content_ciphertext/salt/nonce hold AES-256-GCM output from Stage 3.2's
-- client-side WebCrypto encryption — the server only ever stores and
-- returns ciphertext, never derives or sees the passphrase-derived key.
--
-- No foreign key or view references chunks from here or vice versa —
-- document_id is a plain uuid column (not a `references chunks`), so no
-- join can pull sealed_chunks content into a chunks-based retrieval
-- query by construction. RLS is still scoped to auth.uid() = user_id,
-- same flat pattern as every other table, but that's ownership, not the
-- sealed/unsealed boundary — Stage 3.4 is what keeps sealed content out
-- of retrieval results while sealed.

create table sealed_chunks (
  id uuid primary key default extensions.uuid_generate_v4(),
  document_id uuid not null references documents (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  ordinal integer not null,
  content_ciphertext bytea not null,
  salt bytea not null,
  nonce bytea not null,
  created_at timestamptz not null default now()
);

create index sealed_chunks_user_id_idx on sealed_chunks (user_id);
create index sealed_chunks_document_id_idx on sealed_chunks (document_id);

alter table sealed_chunks enable row level security;

create policy sealed_chunks_select_own on sealed_chunks
  for select using (auth.uid() = user_id);
create policy sealed_chunks_insert_own on sealed_chunks
  for insert with check (auth.uid() = user_id);
create policy sealed_chunks_update_own on sealed_chunks
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy sealed_chunks_delete_own on sealed_chunks
  for delete using (auth.uid() = user_id);
