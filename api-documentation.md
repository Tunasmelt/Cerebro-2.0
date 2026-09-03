# Cerebro 2.0 — API Documentation

Two layers: **third-party APIs** this project depends on (check current
docs before integrating — run `/api-check` first, provider SDKs and
model names change faster than training data) and **Cerebro's own
FastAPI surface**, documented here against the real implementation in
`services/api/app/routes/` — every route below exists and is covered by
tests, not a forward-looking spec.

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
| three.js | WebGL brain-graph rendering (`GraphCanvas.tsx`) — replaced an earlier Canvas 2D + d3-force implementation, see phases-and-gates.md's "3D graph rendering upgrade" | https://threejs.org/docs |

Before wiring any of these in code, confirm current endpoint names, auth
headers, and model identifiers against the live docs — this table is a
map to the source of truth, not a substitute for it.

---

## Cerebro API — spec-level reference

Base path: `/api/v1`. All routes except `/health` require a valid
Supabase JWT (`Authorization: Bearer <token>`), verified in `core/`.
List endpoints return a flat list, own rows only (RLS) — none of them
ended up needing cursor pagination in practice. All routes are
rate-limited per user — see architecture doc for the current limits
table.

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
                                    completion is never trusted alone. A
                                    successful embed at the end of this
                                    background pipeline triggers Stage
                                    2.5's nearest-centroid graph
                                    placement automatically (no separate
                                    call needed) — see
                                    architecture-and-security.md's
                                    "Incremental clustering" section.
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
                                    upload-confirm — including the same
                                    graph-placement trigger on success.
GET    /documents                  Flat list, own documents only (RLS)
                                    — not cursor-paginated in practice;
                                    this project's realistic per-user
                                    document count never needed it, and
                                    no other list endpoint in this API
                                    (chat sessions, graph nodes) is
                                    paginated either.
GET    /documents/{id}             Stage 3.6 — metadata + status, PLUS
                                    ingest_state and last_error folded in
                                    directly (ingest_jobs.state/last_error
                                    for this document) — this replaces
                                    the originally-planned standalone
                                    GET /ingest-jobs/{id} + SSE push
                                    below: the frontend already polls
                                    GET /documents for status (Stage
                                    1.1), so a second endpoint returning
                                    the same kind of data under a
                                    different id space (ingest_jobs.id,
                                    which the frontend never has) added
                                    surface without adding capability.
                                    404 if the document doesn't exist or
                                    isn't the caller's (RLS) — same
                                    404-not-403 pattern as every other
                                    per-document route in this API.
PATCH  /documents/{id}             Body: `{ title }`. Rename. Same
                                    RLS-scoped 404-not-403 pattern.
POST   /documents/{id}/extract-action-items  No body. Vision/text model
                                    call over the document's real
                                    content proposing candidate action
                                    items (title + description) — never
                                    auto-created, the caller still picks
                                    which ones (if any) become real
                                    kanban cards or todos client-side.
POST   /documents/capture          Body: `{ text }`. Quick-capture — a
                                    thought typed directly (not a file
                                    upload) runs through the same
                                    extract → embed pipeline every
                                    uploaded document goes through.
                                    Capped at the same MAX_CAPTURE_CHARS
                                    server enforces, client-side hint
                                    only.
GET    /documents/{id}/seal-salt   Stage 3.3 follow-up — the Argon2id
                                    salt a client needs before it can
                                    even attempt /unlock (every chunk of
                                    a sealed document carries the same
                                    salt, since sealing derives one key
                                    per document, not one per chunk — see
                                    the "multi-chunk sealing" fix in
                                    phases-and-gates.md). Not secret by
                                    cryptographic design — a salt's job
                                    is uniqueness against precomputation,
                                    not confidentiality — so exposing it
                                    doesn't weaken the security model.
                                    404 if nothing is sealed for this
                                    document.
GET    /documents/{id}/download    Stage 3.6 — signed URL (60s TTL) to
                                    the normalized (indexed) file.
                                    **Sealed documents reject this with
                                    423 `document_sealed`, never a
                                    signed URL** — sealing only ever
                                    removed chunk-level plaintext from
                                    the retrieval-path `chunks` table
                                    (Stage 3.3); it was never designed to
                                    re-encrypt the underlying Storage
                                    object, and building this route was
                                    the first time a path existed to
                                    read that object directly at all. A
                                    signed URL bypasses the passphrase
                                    entirely, so this has to fail closed
                                    by construction rather than trust an
                                    unlock-claim header (there is no
                                    mechanism to re-encrypt or gate
                                    Storage's actual bytes transparently
                                    yet — that's future scope, not
                                    solved by this stage).
GET    /documents/{id}/original    Stage 3.6 — signed URL (60s TTL) to
                                    the untouched original. Same sealed-
                                    document rejection as /download,
                                    same reasoning.
DELETE /documents/{id}             Stage 3.6 — deletes both Storage
                                    objects (best-effort — a failed
                                    Storage delete doesn't block removing
                                    the row) then the `documents` row,
                                    which cascades chunks, sealed_chunks,
                                    ingest_jobs, document_clusters,
                                    document_edges, and unlock_claims via
                                    each table's own `on delete cascade`
                                    FK (Stage 0.2/2.1/2.2/3.1/3.3
                                    migrations). Works on sealed
                                    documents too — deleting doesn't
                                    require the passphrase, only
                                    ownership (RLS).
POST   /documents/{id}/seal        Body: `{ chunks: [{ ordinal,
                                    content_ciphertext, salt, nonce }] }`
                                    — base64 AES-256-GCM output the
                                    client already produced (Stage 3.2's
                                    seal.ts); the server never receives a
                                    passphrase or a derived key here.
                                    Moves ciphertext into sealed_chunks,
                                    deletes the plaintext+embedding rows
                                    from `chunks`, sets status=sealed.
                                    409 `not_ready` if ingest hasn't
                                    finished yet (Stage 3.5 — closes a
                                    real race where sealing too early let
                                    an in-flight ingest job re-populate
                                    `chunks` afterward).
POST   /documents/{id}/unlock      Body: `{ key }` — the Argon2id-
                                    derived AES-256-GCM key, this request
                                    only, never persisted. Test-decrypts
                                    one real sealed_chunks row to prove
                                    the key is correct (401 `invalid_key`
                                    if not), then issues a claim (a
                                    Postgres row, not a signed token)
                                    scoped to this one document, expiring
                                    in 15 minutes per Postgres's own
                                    clock.
POST   /documents/{id}/unseal      Body: `{ claim_id, key }` — the key
                                    sent again, this request only.
                                    Validates the claim's document scope
                                    and expiry *before* touching any
                                    ciphertext (401 `claim_expired`, 403
                                    `claim_scope_mismatch`, 404
                                    `claim_not_found`), then decrypts and
                                    returns plaintext in the response
                                    body only — never persisted
                                    server-side.
```

Size enforcement lives at Supabase Storage's bucket-level file size
config, not in this API — any client-side or `upload-init` size check
is UX-only, verified against the actual bytes at `upload-confirm`, and
`uploading` rows that never confirm need an expiry sweep like any other
stalled ingest job.

### Chat / retrieval

```
POST   /chat/sessions              Create a session.
GET    /chat/sessions              List the caller's own sessions, most
                                    recent first (Stage 2.4) — the "past
                                    conversations" picker for replaying
                                    a graph pulse. Each session also
                                    carries `preview` (the session's
                                    first user message, truncated —
                                    chat management pass) for the /chat
                                    page's session list.
DELETE /chat/sessions/{id}         Chat management pass. `chat_messages`
                                    cascades via its own FK — no
                                    separate cleanup needed. RLS-scoped
                                    404-not-403.
GET    /chat/sessions/{id}/messages  History (Stage 2.4), each message's
                                    retrieved_chunk_ids resolved to
                                    retrieved_document_ids server-side —
                                    used to replay the graph pulse
                                    animation for past conversations.
                                    Chunks from the same document
                                    collapse to one document id, not a
                                    duplicate pulse entry. Each assistant
                                    message also carries a resolved
                                    `citations` array (chunk_id,
                                    document_id, document_title — chat
                                    management pass, reuses
                                    `chat/prompt.py`'s real
                                    extract_citations rather than a
                                    second parsing implementation) so a
                                    reopened conversation's citation
                                    chips work exactly like a live one's.
                                    404 if the session doesn't exist or
                                    isn't the caller's own.
GET    /chat/sessions/{id}/messages/{message_id}/prompt  Stage 5.6 — the
                                    real assembled prompt for a past
                                    turn (sections + per-section token
                                    counts) for the playground to render
                                    and let the caller edit.
POST   /chat/sessions/{id}/playground/run  Stage 5.6. Body: the edited
                                    assembly (system_instructions,
                                    context_sections, user_query). Runs
                                    it for real against the live model —
                                    never the normal chat path, and
                                    nothing about an edited run is
                                    persisted. Returns the response plus
                                    real token/cost/latency totals.
POST   /chat/sessions/{id}/agent-turn  Stage 4.5 (stretch). Body:
                                    { message }. A tool-calling turn,
                                    distinct from the plain-generation
                                    playground above — can create real
                                    kanban cards as a side effect,
                                    returned in the response alongside
                                    the model's reply.
POST   /chunks/{id}/link           Stage 5.3. Body: { target_chunk_id }.
                                    An explicit, user-drawn associative
                                    edge between two of the caller's own
                                    chunks — stored `is_explicit=true`,
                                    never decayed, reads as meaningfully
                                    stronger on the graph than any
                                    number of coincidental co-retrievals.
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
GET    /graph/nodes                Document nodes + cluster_id + 3D
                                    centroid position (x/y/z — the "3D
                                    graph rendering upgrade" extended
                                    the original 2D PCA projection to a
                                    third component). Reflects every
                                    status=ready document live —
                                    uploaded-since-last-recluster
                                    documents still appear, with
                                    cluster_id/x/y/z null rather than
                                    being missing.
GET    /graph/edges                kNN edges (3 nearest neighbors per
                                    document at last cluster run) —
                                    computed and stored during
                                    /graph/recluster, not live; this one
                                    DOES lag new uploads until the next
                                    recluster, unlike /graph/nodes.
                                    `?include=associative` also returns
                                    an `associative_edges` array (Stage
                                    5.3/5.4) — document-level edges
                                    aggregated from real chunk
                                    co-retrieval, computed live on every
                                    call (not stored/lagged like the kNN
                                    edges above), weight-filtered so a
                                    single shared retrieval doesn't
                                    render as a permanent edge — see
                                    architecture-and-security.md's
                                    "Associative memory graph" section.
GET    /graph/nodes/{id}/chunks    Chunk satellites for an expanded node.
                                    404 if the document doesn't exist or
                                    isn't the caller's own.
```

### Kanban (Phase 4)

```
POST   /boards                     Body: { title }. columns defaults to
                                    ["Backlog", "In Progress", "Done"].
GET    /boards                     Flat list, own boards only.
GET    /boards/{id}                Board + its cards, ordered by
                                    position within each column.
POST   /boards/{id}/cards          Body: { column_name, title,
                                    description?, document_id? }.
PATCH  /cards/{id}                 Body: any of column_name/position
                                    (the move/reorder call — position is
                                    a float the client computes by
                                    averaging its new neighbors',
                                    Stage 4.1)/title/description.
DELETE /cards/{id}                 RLS-scoped 404-not-403.
```

### Todos (Phase 4)

```
POST   /todos                      Body: { title, document_id? }.
GET    /todos                      Flat list, own todos only.
PATCH  /todos/{id}                 Body: { completed } — completed_at is
                                    always derived server-side, a
                                    client-supplied timestamp is never
                                    trusted.
DELETE /todos/{id}                 RLS-scoped 404-not-403.
```

### Account

```
DELETE /account                    Stage 4.7. Permanently deletes every
                                    document, chat, kanban board, and
                                    task, including sealed documents —
                                    the account itself remains able to
                                    sign in, empty. Profile fields
                                    (display name, avatar URL, email,
                                    password) are updated directly
                                    against Supabase Auth from the
                                    client — no backend route for those.
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
- Sealed-tier failures use distinct codes per cause (`invalid_key`,
  `not_found`, `claim_not_found`, `claim_scope_mismatch`,
  `claim_expired`, `not_ready`, `document_sealed`) rather than one
  generic code — an earlier draft of this doc specified a single
  generic `sealed_locked` code "to avoid leaking why unlock failed,"
  but that reasoning doesn't hold given how these routes are actually
  scoped: every lookup (a claim, a sealed_chunks row) runs with the
  caller's own JWT and is RLS-scoped first, so a nonexistent resource
  and someone else's resource already come back identically (404) by
  construction — a specific code beyond that point (e.g. `invalid_key`
  vs `claim_expired` on the caller's *own* document) reveals nothing an
  attacker didn't already have to prove ownership to see. Stage 3.5's
  adversarial test suite is written around this specific-code contract
  and verifies the RLS-scoping claim directly, live, against production.
- Timestamps: ISO 8601 UTC throughout.
