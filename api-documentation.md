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
| Voyage AI | Text + multimodal embeddings, rerank | https://docs.voyageai.com |
| Cohere | Alternative embed + rerank provider | https://docs.cohere.com |
| Google Gemini | Generation, vision captioning | https://ai.google.dev/gemini-api/docs |
| Langfuse | Tracing, spans, cost/latency observability | https://langfuse.com/docs |
| RAGAS | Faithfulness / relevancy / context-precision eval | https://docs.ragas.io |
| Railway | Deploy, resource limits, env config | https://docs.railway.com |
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
POST   /documents                  Upload a file (multipart). Returns
                                    document id + ingest_job id immediately;
                                    processing is async.
GET    /documents                  List, cursor-paginated. Filterable by
                                    status (processing|ready|failed|sealed).
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
GET    /chat/sessions/{id}         History, including stored
                                    retrieved_chunk_ids per message — used
                                    to replay the graph pulse animation
                                    for past conversations.
POST   /chat/sessions/{id}/stream  SSE. Emits, in order:
                                      event: retrieval
                                        data: { chunk_ids, document_ids }
                                      event: token          (repeated)
                                      event: citation        (repeated)
                                      event: done
                                    The retrieval event MUST arrive before
                                    the first token event — the graph
                                    pulse depends on this ordering.
```

### Graph

```
GET    /graph/nodes                Document nodes + cluster_id + 2D
                                    centroid position.
GET    /graph/edges                kNN edges (3 nearest neighbors per
                                    document at last cluster run).
GET    /graph/nodes/{id}/chunks    Chunk satellites for an expanded node.
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
                                    Used for Railway health checks and
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
