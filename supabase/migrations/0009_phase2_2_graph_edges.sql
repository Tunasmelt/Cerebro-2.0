-- Stage 2.2 — kNN graph edges. No edges table existed anywhere in the
-- docs before this stage; api-documentation.md's own wording for
-- GET /graph/edges ("kNN edges... at last cluster run") implies edges
-- are computed once during clustering and read back, not recomputed
-- live per request — resolved in conversation, extending Stage 2.1's
-- clustering job to compute and persist these alongside cluster
-- assignments, in the same run, from the same document centroid
-- vectors, rather than a separate live computation that could drift
-- out of sync with the node positions.

create table document_edges (
  document_id uuid not null references documents (id) on delete cascade,
  neighbor_document_id uuid not null references documents (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  distance double precision not null,
  rank integer not null,  -- 1..3, nearest first
  primary key (document_id, neighbor_document_id)
);

create index document_edges_document_id_idx on document_edges (document_id);
create index document_edges_user_id_idx on document_edges (user_id);

alter table document_edges enable row level security;

create policy document_edges_select_own on document_edges
  for select using (auth.uid() = user_id);
create policy document_edges_insert_own on document_edges
  for insert with check (auth.uid() = user_id);
create policy document_edges_delete_own on document_edges
  for delete using (auth.uid() = user_id);
