-- Stage 1.5 — hybrid retrieval needs two RPC functions because PostgREST's
-- plain table query syntax can't order by a computed expression (cosine
-- distance to a query vector, or FTS rank) — only by real columns. Both
-- functions are SECURITY INVOKER (Postgres's default), so RLS still
-- applies exactly as it does to direct table access — a function calling
-- as user A can never surface user B's chunks, same as any other query.

create or replace function match_chunks_vector(
  query_embedding halfvec(1024),
  match_count int
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
as $$
  select
    chunks.id,
    chunks.document_id,
    chunks.ordinal,
    chunks.content,
    chunks.meta,
    chunks.embedding <=> query_embedding as distance
  from chunks
  where chunks.embedding is not null
  order by chunks.embedding <=> query_embedding
  limit match_count;
$$;

create or replace function match_chunks_fts(
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
as $$
  select
    chunks.id,
    chunks.document_id,
    chunks.ordinal,
    chunks.content,
    chunks.meta,
    ts_rank(chunks.content_tsv, websearch_to_tsquery('english', query_text)) as rank
  from chunks
  where chunks.content_tsv @@ websearch_to_tsquery('english', query_text)
  order by rank desc
  limit match_count;
$$;
