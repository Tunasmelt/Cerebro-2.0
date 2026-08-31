# CLAUDE.md — Cerebro 2.0

Context for any Claude session (chat, Code, or an agent) working in this
repo. Read this before touching code. Companion docs: `docs/phases-and-gates.md`,
`docs/architecture-and-security.md`, `docs/api-documentation.md`.

## What this is

A personal multimodal knowledge vault. Documents and images are ingested,
normalized, chunked, and embedded; a hybrid retriever (vector + full-text,
fused with RRF, then reranked) answers natural-language questions with
citations back to source chunks. A force-directed "brain graph" visualizes
real retrieval as it happens — nodes pulse only when they were actually
returned by the retriever, replayed from stored `retrieved_chunk_ids`, never
simulated. Files can be sealed behind a passphrase (metadata stays
searchable, content does not, until unlocked).

## Non-negotiable constraints

- **Render free tier: 512MB RAM, 0.1 CPU, no card required.** This is
  where the FastAPI service actually runs (switched from Render, whose
  free trial expired mid-build). Free tier sleeps after 15 minutes idle
  — expect 30-60s cold starts on the first request after idle time.
  Fine during Phase 0-2 build-out; budget the $7/month Starter plan
  before any live demo where cold start would be visible to someone
  other than you. Background/worker processes outside the request cycle
  are not covered by the free tier — our ingest pipeline runs in-process
  within the web service specifically so it stays inside this tier;
  don't split it into a separate worker without revisiting this.
  This RAM ceiling still governs library choices (no torch, no local
  embedding models, no heavy transitive deps) and processing patterns
  (streaming I/O, draft-mode image decode, concurrency=1 on the ingest
  worker). See `architecture-and-security.md` §Memory Governance before
  adding any dependency that touches PDFs or images.
- **Supabase free tier**: ~500MB Postgres, ~1GB storage. Two separate
  storage buckets exist on purpose — `indexed` (normalized, what retrieval
  reads) and `originals` (untouched uploads, retrieval never reads this).
  Don't merge them.
- **Sealed content is metadata-only until unlocked.** Never let a sealed
  document's chunk text enter the retrieval index in plaintext, and never
  let embedding vectors for sealed content exist outside the isolated
  `sealed_chunks` table.
- **The passphrase-derived key is client-side (WebCrypto) and never
  persisted.** There is no recovery flow. Don't add one without a full
  team discussion — it would change the security model this product is
  built on.

## Stack

Next.js 15 (Vercel) → FastAPI (Render) → Supabase (Postgres + pgvector +
storage + auth). Embeddings/generation/rerank are hosted API calls only —
embeddings use Jina (`jina-embeddings-v5-omni`, chosen in Stage 1.4 over
Voyage/Cohere for its broader multimodal span — text/image/audio/video/PDF
in one shared vector space — plus an explicit free tier; Voyage
(`voyage-multimodal-3.5`) and Cohere (`embed-v4.0`) remain viable
documented alternatives if Jina's terms or limits ever stop working) —
plus a hosted reranker, Gemini for generation. Observability: Langfuse
tracing on every retrieval span, RAGAS as a CI
regression gate.

## Build order (see phases-and-gates.md for full detail)

RAG core → brain graph → sealed tier → kanban/todo/playground. This order
is load-bearing: the graph renders real vectors, so ingestion must exist
first; sealing gates artifacts ingestion produces, so it comes after.
Retrieval core is a deliberate fork of the existing Docify pipeline
(hybrid + RRF + citation verification) — don't rebuild it from scratch.

## Before writing ingest/retrieval code

- Check `architecture-and-security.md` for the current schema —
  particularly `halfvec` usage, the `sealed_chunks` isolation, and the
  `schema_version` column on `documents` (chunking strategy changes must
  not silently invalidate old sealed content).
- Run `/api-check` before touching any embedding, rerank, or generation
  API call — provider SDKs change frequently and training data goes stale.
- New PDF/image-handling code must go through `/security-check` before
  merge (file-upload category) and must be reviewed against the Memory
  Governance guardrails in the architecture doc.

## Testing & CI gate

lint → unit tests (chunking, RRF fusion) → integration tests (seeded
Supabase test project) → RAGAS regression check against the stored
baseline → build. Any red step blocks merge to `main`.

## Naming discipline

Call the sealed-file feature "sealed" or "passphrase-gated," not
"encrypted" in isolation, and never "zero-knowledge" — the derived key
does transit to the server per request during an active unlock session.
The security marketing page and this file must always agree on that
sentence.
