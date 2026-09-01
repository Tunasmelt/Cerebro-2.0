-- Stage 2.1 — clustering job schema, per architecture-and-security.md
-- §2's already-documented shape: clusters (centroid position + label)
-- and document_clusters (which document belongs to which cluster, plus
-- its distance to that cluster's centroid). RLS follows the same flat
-- auth.uid() = user_id pattern as every other table — document_clusters
-- gets its own denormalized user_id for the same reason ingest_jobs and
-- chat_messages do (Stage 0.2/1.1): a flat check, no join required, and
-- ownership never transfers between users.

create table clusters (
  id uuid primary key default extensions.uuid_generate_v4(),
  user_id uuid not null references auth.users (id) on delete cascade,
  label text,
  centroid_x double precision not null,
  centroid_y double precision not null,
  method text not null default 'kmeans+pca',
  computed_at timestamptz not null default now()
);

create index clusters_user_id_idx on clusters (user_id);

alter table clusters enable row level security;

create policy clusters_select_own on clusters
  for select using (auth.uid() = user_id);
create policy clusters_insert_own on clusters
  for insert with check (auth.uid() = user_id);
create policy clusters_update_own on clusters
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy clusters_delete_own on clusters
  for delete using (auth.uid() = user_id);

create table document_clusters (
  document_id uuid not null references documents (id) on delete cascade,
  cluster_id uuid not null references clusters (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  distance double precision not null,
  primary key (document_id)
  -- one cluster per document, not many — a full re-cluster run (this
  -- stage's approach; Stage 2.5 adds incremental placement) upserts this
  -- row rather than accumulating history.
);

create index document_clusters_cluster_id_idx on document_clusters (cluster_id);
create index document_clusters_user_id_idx on document_clusters (user_id);

alter table document_clusters enable row level security;

create policy document_clusters_select_own on document_clusters
  for select using (auth.uid() = user_id);
create policy document_clusters_insert_own on document_clusters
  for insert with check (auth.uid() = user_id);
create policy document_clusters_update_own on document_clusters
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy document_clusters_delete_own on document_clusters
  for delete using (auth.uid() = user_id);
