# Cerebro 2.0 — API Documentation

Two layers: **third-party APIs** this project depends on (check current
docs before integrating — run `/api-check` first, provider SDKs and
model names change faster than training data) and **Cerebro's own FastAPI
surface**, documented at a spec level here since the implementation
doesn't exist yet.

---

## Third-party API references

| Provider | Used for | Docs |
|---|---|---|
| Supabase | Postgres, pgvector, storage, auth, RLS | https://supabase.com/docs |
| Supabase — pgvector guide | halfvec, HNSW indexing | https://supabase.com/docs/guides/ai/vector-columns |
| Jina AI | Text + multimodal (image/audio/video/PDF) embeddings — adopted Stage 1.4 | https://jina.ai/embeddings/ |
| Voyage AI | Text + multimodal embeddings, rerank — documented fallback | https://docs.voyageai.com |
| Cohere | Reranking (rerank-v4.0-pro) — adopted Stage 1.5; also a documented embed fallback | https://docs.cohere.com |
| Google Gemini | Generation, vision captioning | https://ai.google.dev/gemini-api/docs |
| Langfuse | Tracing, spans, cost/latency observability | https://langfuse.com/docs |
| RAGAS | Faithfulness / relevancy / context-precision eval | https://docs.ragas.io |
| Render | Deploy, resource limits, env config | https://render.com/docs |
| Vercel | Next.js hosting, edge functions | https://vercel.com/docs |
| Next.js | App router, route handlers (BFF proxy layer) | https://nextjs.org/docs |
| FastAPI | Route/middleware patterns | https://fastapi.tiangolo.com |
| pikepdf | Lossless PDF structural optimization | https://pikepdf.readthedocs.io |
| Pillow | Image decode/resize, draft-mode | https://pillow.readthedocs.io |
| react-force-graph | Graph rendering | https://github.com/vasturiano/react-force-graph |

Before wiring any of these in code, confirm current endpoint names, auth
headers, and model identifiers against the live docs — this table is a
map to the source of truth, not a substitute for it.

---

## Cerebro API — spec-level reference

Base path: `/api/v1`. All routes except `/health` require a valid
Supabase JWT (`Authorization: Bearer <token>`), verified in `core/`.
All list endpoints are cursor-paginated. All routes are rate-limited per
user — see architecture doc for the current limits table.

### Documents

```
POST   /documents/upload-init      Body: filename, mime, size_bytes.
                                    Creates the documents row (status=
                                    uploading) and ingest_jobs row BEFORE
                                    any signed URL exists — never the
                                    reverse, or a failed upload orphans a
                                    row with nothing behind it. Returns
                                    document id + a short-lived Supabase
                                    signed upload URL scoped to
                                    originals/{user_id}/{document_id}/
                                    original.{ext}. File bytes never pass
                                    through this API — the browser
                                    uploads directly to Supabase Storage
                                    with the returned URL (Vercel/Render
                                    both have body limits well under the
                                    50MB cap — itself Supabase Free's
                                    platform ceiling, not a design choice
                                    — so this can't be a proxy).
POST   /documents/{id}/upload-confirm  No body. Server verifies the
                                    object actually exists in storage
                                    (existence + size via Supabase admin
                                    API) before advancing the job past
                                    uploading — the client's claim of
                                    completion is never trusted alone.
POST   /documents/{id}/retry-ingest  No body. Retries a failed job, but
                                    only if it failed during embed —
                                    proxied by chunks already existing
                                    for the document (extract completed).
                                    404 if no job exists, 409 if the job
                                    isn't in state=failed or failed before
                                    any chunk was extracted (normalize/
                                    extract retry isn't safe yet — see
                                    embed.py's check_retry_eligible).
                                    202 + state=embedding on success, with
                                    the actual retry running in the
                                    background, same pattern as
                                    upload-confirm.
GET    /documents                  List, cursor-paginated. Filterable by
                                    status (processing|ready|failed|
                                    sealed) — "uploading" is an
                                    ingest_jobs.state value, not a
                                    documents.status value; a document is
                                    "processing" for its entire ingest
                                    pipeline, uploading included.
GET    /documents/{id}             Metadata + status.
GET    /documents/{id}/download    Signed URL to the normalized (indexed)
                                    file. Sealed documents require a valid
                                    unlock claim header.
GET    /documents/{id}/original    Signed URL to the untouched original.
DELETE /documents/{id}             Removes document, chunks, vectors,
                                    both storage objects.
POST   /documents/{id}/seal        Body: passphrase. Moves chunks into
                                    sealed_chunks, re-encrypts file.
POST   /documents/{id}/unseal      Body: passphrase. Issues a session-
                                    scoped unlock claim (15 min).
```

Size enforcement lives at Supabase Storage's bucket-level file size
config, not in this API — any client-side or `upload-init` size check
is UX-only, verified against the actual bytes at `upload-confirm`, and
`uploading` rows that never confirm need an expiry sweep like any other
stalled ingest job.

### Ingest jobs

```
GET    /ingest-jobs/{id}           Poll status + current pipeline stage
                                    (uploading|normalizing|extracting|
                                    embedding|ready|failed) + last_error
                                    if failed. Also pushed via SSE — see
                                    below.
```

### Chat / retrieval

```
POST   /chat/sessions              Create a session.
GET    /chat/sessions              List the caller's own sessions, most
                                    recent first (Stage 2.4) — the "past
                                    conversations" picker for replaying
                                    a graph pulse.
GET    /chat/sessions/{id}/messages  History (Stage 2.4), each message's
                                    retrieved_chunk_ids resolved to
                                    retrieved_document_ids server-side —
                                    used to replay the graph pulse
                                    animation for past conversations.
                                    Chunks from the same document
                                    collapse to one document id, not a
                                    duplicate pulse entry. 404 if the
                                    session doesn't exist or isn't the
                                    caller's own.
POST   /chat/sessions/{id}/stream  Body: { query }. SSE. Emits, in order:
                                      event: retrieval
                                        data: { chunk_ids, document_ids }
                                      event: token          (repeated)
                                        data: { text }
                                      event: citation        (repeated)
                                        data: { chunk_id, document_id }
                                      event: done
                                    ...or, if anything fails partway
                                    through (retrieval, generation,
                                    storage), in place of the rest:
                                      event: error
                                        data: { code, message }
                                    (no done after an error — the stream
                                    just ends). Added after a live audit
                                    caught a real production case: a
                                    Gemini call that timed out mid-
                                    generation used to just kill the
                                    connection with nothing after
                                    `retrieval` — no error, no done, no
                                    way for the client to tell "failed"
                                    from "still working".
                                    The retrieval event MUST arrive before
                                    the first token event — the graph
                                    pulse depends on this ordering; this
                                    is structural (retrieve() is fully
                                    awaited first), not just observed.
                                    Citations come from the model citing
                                    inline with [[chunk:<id>]] markers —
                                    any marker naming an id outside the
                                    real retrieved set is dropped, never
                                    forwarded. 404 if the session doesn't
                                    exist or isn't the caller's own.
```

### Graph

```
POST   /graph/recluster            No body. Triggers a full re-cluster
                                    (Stage 2.1) as a background task,
                                    same in-process pattern as the
                                    ingest pipeline. 202 immediately;
                                    the actual k-means + PCA run happens
                                    after the response is sent. Always a
                                    full recompute for now — Stage 2.5
                                    adds incremental placement.
GET    /graph/nodes                Document nodes + cluster_id + 2D
                                    centroid position. Reflects every
                                    status=ready document live —
                                    uploaded-since-last-recluster
                                    documents still appear, with
                                    cluster_id/x/y null rather than
                                    being missing.
GET    /graph/edges                kNN edges (3 nearest neighbors per
                                    document at last cluster run) —
                                    computed and stored during
                                    /graph/recluster, not live; this one
                                    DOES lag new uploads until the next
                                    recluster, unlike /graph/nodes.
GET    /graph/nodes/{id}/chunks    Chunk satellites for an expanded node.
                                    404 if the document doesn't exist or
                                    isn't the caller's own.
```

### Playground (Phase 4)

```
POST   /playground/assemble        Body: session_id, query. Returns the
                                    editable prompt assembly (sections,
                                    token counts per section).
POST   /playground/run             Body: edited assembly. Runs it as-is,
                                    returns the model response + actual
                                    token/cost totals.
```

### Health

```
GET    /health                     No auth. Returns 200 + build sha.
                                    Used for Render health checks and
                                    keep-warm pings.
```

---

## Response conventions

- Errors: `{ "error": { "code": "...", "message": "..." } }`, never a raw
  stack trace or exception string in the body — matches the UI rule of
  never showing raw errors to the user.
- Sealed-content failures return a generic `sealed_locked` code
  regardless of *why* the unlock failed (wrong passphrase vs. malformed
  request) — this is a deliberate security choice, not an omission; see
  architecture doc, manual-review item `escape-user-content` /
  rate-limit discussion.
- Timestamps: ISO 8601 UTC throughout.
