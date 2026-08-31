-- Embedding provider fallback (Jina -> Voyage -> Cohere), added after
-- Stage 1.4 as new scope. Different providers produce incompatible
-- vector spaces even at the same dimension, so a document's vectors
-- must all come from one provider, and vector search must never compare
-- across providers. embedding_provider is set once a document's job
-- locks onto a provider (its first successfully-embedded chunk) and
-- never changes after that for the document's life; a fresh document
-- with no embeddings yet defaults to 'jina' (the primary provider),
-- matching every retrieval query, which always embeds with the primary
-- client.

alter table documents
  add column embedding_provider text not null default 'jina'
    check (embedding_provider in ('jina', 'voyage', 'cohere'));

-- A 3rd parameter isn't an overload PostgREST/Postgres can disambiguate
-- cleanly against the old 2-arg signature once it has a default, so the
-- old function is dropped and replaced outright rather than left as a
-- second overload.
drop function if exists match_chunks_vector(halfvec(1024), int);

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
  order by chunks.embedding <=> query_embedding
  limit match_count;
$$;
