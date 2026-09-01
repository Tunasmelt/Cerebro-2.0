-- Stage 3.4 — metadata-only search filtering. Sealing already deletes a
-- document's rows from `chunks` (Stage 3.3's seal_document), so sealed
-- content is structurally absent from these RPC functions' source table
-- already — this migration adds an explicit `documents.status <> 'sealed'`
-- filter as defense-in-depth, so retrieval can never surface sealed
-- content even if a future bug ever left a stale chunks row behind.
--
-- match_chunks_vector already joined documents (Stage 1.4's provider
-- fallback migration) — this just adds one more condition to that
-- existing join. match_chunks_fts never joined documents before; this
-- adds the join.

drop function if exists match_chunks_vector(halfvec(1024), int, text);

create function match_chunks_vector(
  query_embedding halfvec(1024),
  match_count int,
  primary_provider text default 'jina'
)
returns table (
  id uuid,
  document_id uuid,
  ordinal int,
  content text,
  meta jsonb,
  distance float
)
language sql
stable
set search_path = public, extensions
as $$
  select
    chunks.id,
    chunks.document_id,
    chunks.ordinal,
    chunks.content,
    chunks.meta,
    chunks.embedding <=> query_embedding as distance
  from chunks
  join documents on documents.id = chunks.document_id
  where chunks.embedding is not null
    and documents.embedding_provider = primary_provider
    and documents.status <> 'sealed'
  order by chunks.embedding <=> query_embedding
  limit match_count;
$$;

drop function if exists match_chunks_fts(text, int);

create function match_chunks_fts(
  query_text text,
  match_count int
)
returns table (
  id uuid,
  document_id uuid,
  ordinal int,
  content text,
  meta jsonb,
  rank float
)
language sql
stable
set search_path = public, extensions
as $$
  select
    chunks.id,
    chunks.document_id,
    chunks.ordinal,
    chunks.content,
    chunks.meta,
    ts_rank(chunks.content_tsv, websearch_to_tsquery('english', query_text)) as rank
  from chunks
  join documents on documents.id = chunks.document_id
  where chunks.content_tsv @@ websearch_to_tsquery('english', query_text)
    and documents.status <> 'sealed'
  order by rank desc
  limit match_count;
$$;
