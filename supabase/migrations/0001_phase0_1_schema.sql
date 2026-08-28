-- Stage 0.2 — Phase 0/1 tables, RLS scoped to auth.uid() = user_id.
-- Tables in scope: documents, chunks, ingest_jobs, chat_sessions, chat_messages.
-- (image_vectors is Phase 2+, sealed_chunks is Phase 3 — not created here.)
--
-- ingest_jobs.user_id and chat_messages.user_id are denormalized (not listed
-- in architecture-and-security.md's column list) so RLS can be a flat
-- auth.uid() = user_id check on every table, per the doc's security review
-- section. chat_sessions is not in the documented data model at all; it's
-- added here as the minimal table chat_messages.session_id and the
-- documented POST /chat/sessions endpoint both require.

create extension if not exists "uuid-ossp" with schema extensions;
create extension if not exists vector;

-- documents ------------------------------------------------------------

create table documents (
  id uuid primary key default extensions.uuid_generate_v4(),
  user_id uuid not null references auth.users (id) on delete cascade,
  title text not null,
  mime text not null,
  size_bytes bigint not null,
  storage_path text,
  original_storage_path text,
  original_size_bytes bigint,
  quality_policy text not null default 'visually_lossless',
  status text not null default 'processing'
    check (status in ('processing', 'ready', 'failed', 'sealed')),
  schema_version integer not null default 1,
  created_at timestamptz not null default now()
);

create index documents_user_id_idx on documents (user_id);

alter table documents enable row level security;

create policy documents_select_own on documents
  for select using (auth.uid() = user_id);
create policy documents_insert_own on documents
  for insert with check (auth.uid() = user_id);
create policy documents_update_own on documents
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy documents_delete_own on documents
  for delete using (auth.uid() = user_id);

-- chunks -----------------------------------------------------------------

create table chunks (
  id uuid primary key default extensions.uuid_generate_v4(),
  document_id uuid not null references documents (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  ordinal integer not null,
  content text not null,
  content_tsv tsvector generated always as (to_tsvector('english', content)) stored,
  embedding halfvec(1024),
  meta jsonb not null default '{}'::jsonb
);

create index chunks_user_id_idx on chunks (user_id);
create index chunks_document_id_idx on chunks (document_id);
create index chunks_content_tsv_idx on chunks using gin (content_tsv);
create index chunks_embedding_hnsw_idx on chunks
  using hnsw (embedding halfvec_cosine_ops);

alter table chunks enable row level security;

create policy chunks_select_own on chunks
  for select using (auth.uid() = user_id);
create policy chunks_insert_own on chunks
  for insert with check (auth.uid() = user_id);
create policy chunks_update_own on chunks
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy chunks_delete_own on chunks
  for delete using (auth.uid() = user_id);

-- ingest_jobs --------------------------------------------------------------

create table ingest_jobs (
  id uuid primary key default extensions.uuid_generate_v4(),
  document_id uuid not null references documents (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  state text not null default 'uploading'
    check (state in ('uploading', 'normalizing', 'extracting', 'embedding', 'ready', 'failed')),
  attempt integer not null default 1,
  checkpoint jsonb not null default '{}'::jsonb,
  last_error text,
  created_at timestamptz not null default now()
);

create index ingest_jobs_user_id_idx on ingest_jobs (user_id);
create index ingest_jobs_document_id_idx on ingest_jobs (document_id);

alter table ingest_jobs enable row level security;

create policy ingest_jobs_select_own on ingest_jobs
  for select using (auth.uid() = user_id);
create policy ingest_jobs_insert_own on ingest_jobs
  for insert with check (auth.uid() = user_id);
create policy ingest_jobs_update_own on ingest_jobs
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy ingest_jobs_delete_own on ingest_jobs
  for delete using (auth.uid() = user_id);

-- chat_sessions --------------------------------------------------------

create table chat_sessions (
  id uuid primary key default extensions.uuid_generate_v4(),
  user_id uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now()
);

create index chat_sessions_user_id_idx on chat_sessions (user_id);

alter table chat_sessions enable row level security;

create policy chat_sessions_select_own on chat_sessions
  for select using (auth.uid() = user_id);
create policy chat_sessions_insert_own on chat_sessions
  for insert with check (auth.uid() = user_id);
create policy chat_sessions_update_own on chat_sessions
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy chat_sessions_delete_own on chat_sessions
  for delete using (auth.uid() = user_id);

-- chat_messages ------------------------------------------------------------

create table chat_messages (
  id uuid primary key default extensions.uuid_generate_v4(),
  session_id uuid not null references chat_sessions (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null,
  retrieved_chunk_ids uuid[] not null default '{}',
  trace_id text,
  created_at timestamptz not null default now()
);

create index chat_messages_user_id_idx on chat_messages (user_id);
create index chat_messages_session_id_idx on chat_messages (session_id);

alter table chat_messages enable row level security;

create policy chat_messages_select_own on chat_messages
  for select using (auth.uid() = user_id);
create policy chat_messages_insert_own on chat_messages
  for insert with check (auth.uid() = user_id);
create policy chat_messages_update_own on chat_messages
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy chat_messages_delete_own on chat_messages
  for delete using (auth.uid() = user_id);
