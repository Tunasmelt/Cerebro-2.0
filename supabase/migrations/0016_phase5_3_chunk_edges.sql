-- Stage 5.3 — associative memory graph (persistent chunk edges). Two
-- sources, both landing in the same table: retrieval co-occurrence
-- (every real chat turn's final result set reinforces every pair of
-- chunks that landed in it together — free, derived entirely from data
-- chat/stream.py already computes) and explicit user-drawn links
-- (is_explicit = true, never decayed). Undirected by construction:
-- source_chunk_id/target_chunk_id are always stored in a canonical
-- (lexicographically smaller, larger) order by the application layer,
-- so a pair is ever represented by exactly one row regardless of which
-- chunk was "first" in a given retrieval — the unique constraint below
-- is what actually enforces that, not application discipline alone.
--
-- No decay column or scheduled job: decay is a pure function of
-- (weight, last_reinforced_at) computed at read time (see
-- app/graph/edges.py's decay_weight) rather than written back on a
-- schedule — simpler than a background worker (which this project's
-- Render free tier doesn't have room for anyway, per CLAUDE.md) and
-- avoids a write on every read. An is_explicit row's stored weight is
-- what's always returned, unchanged.
--
-- Sealed content can never appear here by construction, not by an
-- added filter: sealing (Stage 3.3) deletes a document's `chunks` rows
-- entirely, so there is no chunk id left to reference once sealed, and
-- the foreign keys below would reject an insert against a row that no
-- longer exists.

create table chunk_edges (
  id uuid primary key default extensions.uuid_generate_v4(),
  user_id uuid not null references auth.users (id) on delete cascade,
  source_chunk_id uuid not null references chunks (id) on delete cascade,
  target_chunk_id uuid not null references chunks (id) on delete cascade,
  weight double precision not null default 0,
  co_retrieval_count integer not null default 0,
  is_explicit boolean not null default false,
  last_reinforced_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint chunk_edges_distinct_chunks check (source_chunk_id <> target_chunk_id),
  constraint chunk_edges_unique_pair unique (user_id, source_chunk_id, target_chunk_id)
);

create index chunk_edges_user_id_idx on chunk_edges (user_id);
create index chunk_edges_source_chunk_id_idx on chunk_edges (source_chunk_id);
create index chunk_edges_target_chunk_id_idx on chunk_edges (target_chunk_id);

alter table chunk_edges enable row level security;

create policy chunk_edges_select_own on chunk_edges
  for select using (auth.uid() = user_id);
create policy chunk_edges_insert_own on chunk_edges
  for insert with check (auth.uid() = user_id);
create policy chunk_edges_update_own on chunk_edges
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy chunk_edges_delete_own on chunk_edges
  for delete using (auth.uid() = user_id);
