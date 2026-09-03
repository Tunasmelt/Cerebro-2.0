"""Stage 1.4 — embed & job state machine (embedding step).

Host-agnostic, same design as normalize.py/extract.py. Uses Jina for
embeddings — adopted over Voyage/Cohere in Stage 1.4 for its broader
multimodal span and an explicit free tier (see CLAUDE.md §Stack).
Confirmed live against the real API before writing this, not from
memory: both jina-embeddings-v5-text-small (text) and
jina-embeddings-v5-omni-small (image) return 1024-dim vectors, matching
chunks.embedding halfvec(1024) exactly — no schema change needed. Also
confirmed PostgREST accepts a plain JSON array for the halfvec column
directly (not something to assume — pgvector types aren't native JSON).

Checkpointing: after each chunk is embedded, ingest_jobs.checkpoint is
updated with the last completed ordinal, so a crash mid-job resumes from
there instead of re-embedding already-done chunks.

Post-launch fix: Jina v5's retrieval is an asymmetric bi-encoder — the
API takes a `task` field selecting a task-specific LoRA adapter
("retrieval.passage" for indexed content, "retrieval.query" for a live
search query; confirmed live against Jina's current docs, not assumed).
The original code sent no `task` at all, silently falling back to
whatever Jina's default adapter is for every call — indexed content and
live queries alike. Confirmed live in production: a real image chunk
(embedding genuinely present, ingest completed cleanly) ranked 16th of
27 total chunks for the query "explain the image" — nowhere near
VECTOR_CANDIDATES' effective window once RRF-fused with FTS, so it
never reached rerank or got cited. `embed_text`/`embed_image` now
default to `task="retrieval.passage"` (what every ingest call needs)
and `retrieve.py`'s query embedding explicitly passes
`task="retrieval.query"`. All chunks embedded before this fix were
embedded without a task adapter and should be re-embedded for
consistency with the corrected asymmetric scheme — see the fix's PR for
the one-off re-embed run against production.

The fallback providers have the same asymmetry and are handled too:
Cohere's `input_type` ("search_document"/"search_query") and Voyage's
`input_type` ("document"/"query") are both mapped from the same `task`
vocabulary. Voyage's mapping was missed in this fix's first draft — a
comment there wrongly claimed Voyage's multimodal API had no query/
document distinction, an assumption never actually checked against
Voyage's docs; caught only because the user asked "what about Cohere
and Voyage" after the Jina fix shipped, not by anything in this repo.
Low real-world severity today regardless, since `retrieve()` only
vector-searches `documents.embedding_provider = jina` chunks — a
document that fell back to Voyage/Cohere is invisible to vector search
entirely, fallback-provider correctness only matters if that scoping
ever changes.

Stage 7.2 — image chunk captioning: extract.py leaves image chunk
`content` empty (see that module's docstring), which meant FTS could
never match an image chunk at all — only vector search could ever
surface one, and retrieve.py had to paper over it with a query-time-only
caption (retrieve/image_caption.py) that isn't persisted and costs a
Gemini call on every retrieval touching an uncaptioned image. Now the
whole document image is captioned once here, at ingest time, via the
same Gemini call (`caption_image_bytes`, factored out of
retrieve/image_caption.py so both share one implementation), and the
result is written into every one of that document's image chunks'
`content` — real, persisted, FTS-matchable text. Best-effort: a caption
failure (already returns None, never raises) just leaves `content`
empty exactly as before, and retrieve.py's query-time fallback still
covers that case and every chunk ingested before this stage existed.

Concurrency=1 via the pipeline-wide lock in app/ingest/concurrency.py.

Provider fallback (added after Stage 1.4, as new scope): Jina -> Voyage
-> Cohere. Different providers are NOT vector-space-compatible even at
the same dimension, so mixing them within one document (or across the
corpus in a way retrieval can't tell apart) would silently corrupt
similarity search. The fallback is therefore whole-job-before-first-
chunk only: if the primary provider fails on a document's very first
chunk, the next provider in the chain is tried for that same chunk; once
any provider succeeds, the document is locked to it
(documents.embedding_provider, supabase/migrations/0007) for every
remaining chunk and for any future resumed run — no more switching once
even one chunk has committed. A locked-provider failure just fails the
job as before; it does not cascade further. Query-time embedding
(retrieve.py) always uses the primary client only — falling back there
would only produce vectors incomparable to the corpus, which isn't a
fix, so a primary-provider outage at query time fails honestly instead.
Voyage (voyage-multimodal-3.5) and Cohere (embed-v4.0) dims/request
shapes confirmed against their live docs before writing these clients,
both explicitly asked for 1024-dim output via output_dimension to match
chunks.embedding halfvec(1024) — Voyage defaults to 1024 already, Cohere
defaults to 1536 and must be told otherwise.
"""
import base64
import io
import os
from typing import Any, Protocol

from PIL import Image

from app.core.http_client import CachedHttpClientMixin
from app.ingest.concurrency import INGEST_LOCK
from app.retrieve.image_caption import caption_image_bytes

TEXT_MODEL = "jina-embeddings-v5-text-small"
IMAGE_MODEL = "jina-embeddings-v5-omni-small"
EMBEDDING_DIMENSIONS = 1024  # must match chunks.embedding halfvec(1024)
JINA_EMBEDDINGS_URL = "https://api.jina.ai/v1/embeddings"

VOYAGE_MULTIMODAL_URL = "https://api.voyageai.com/v1/multimodalembeddings"
VOYAGE_MODEL = "voyage-multimodal-3.5"

COHERE_EMBED_URL = "https://api.cohere.com/v2/embed"
COHERE_EMBED_MODEL = "embed-v4.0"

PROVIDER_JINA = "jina"
PROVIDER_VOYAGE = "voyage"
PROVIDER_COHERE = "cohere"


class EmbedError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def crop_tile(original_bytes: bytes, bbox: list[int]) -> bytes:
    img = Image.open(io.BytesIO(original_bytes))
    img.load()
    tile = img.crop(tuple(bbox))
    if tile.mode not in ("RGB", "RGBA"):
        tile = tile.convert("RGB")
    out = io.BytesIO()
    tile.save(out, format="PNG")
    return out.getvalue()


class EmbedClient(Protocol):
    provider: str

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]: ...
    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]: ...


class JinaEmbedClient(CachedHttpClientMixin):
    provider = PROVIDER_JINA

    def __init__(self) -> None:
        self._api_key = os.environ.get("JINA_API_KEY", "")

    async def _call(self, model: str, input_item: dict[str, str], task: str) -> list[float]:
        client = self._client()
        response = await client.post(
            JINA_EMBEDDINGS_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": [input_item], "task": task},
        )
        if response.status_code >= 400:
            raise EmbedError("embed_call_failed", response.text)
        return response.json()["data"][0]["embedding"]

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        return await self._call(TEXT_MODEL, {"text": text}, task)

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        b64 = base64.b64encode(image_bytes).decode()
        return await self._call(IMAGE_MODEL, {"image": f"data:image/png;base64,{b64}"}, task)


class VoyageEmbedClient(CachedHttpClientMixin):
    """First fallback. voyage-multimodal-3.5 defaults to 1024-dim output
    (still passed explicitly), so no schema mismatch vs. Jina's 1024-dim
    — but the vector *space* still differs, hence the whole-job lock."""

    provider = PROVIDER_VOYAGE

    def __init__(self) -> None:
        self._api_key = os.environ.get("VOYAGE_API_KEY", "")

    async def _call(self, content_item: dict[str, str], task: str) -> list[float]:
        # Confirmed live against Voyage's current multimodal-embeddings
        # docs (not assumed from memory, and not assumed to be absent
        # either — an earlier version of this fix wrongly claimed Voyage
        # had no query/document asymmetry at all): input_type "query" vs
        # "document" prepends a different task-specific instruction
        # before vectorizing, same asymmetric-retrieval shape as Jina's
        # task and Cohere's input_type.
        input_type = "query" if task == "retrieval.query" else "document"
        client = self._client()
        response = await client.post(
            VOYAGE_MULTIMODAL_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "inputs": [{"content": [content_item]}],
                "model": VOYAGE_MODEL,
                "input_type": input_type,
                "output_dimension": EMBEDDING_DIMENSIONS,
            },
        )
        if response.status_code >= 400:
            raise EmbedError("embed_call_failed", response.text)
        return response.json()["data"][0]["embedding"]

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        return await self._call({"type": "text", "text": text}, task)

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        b64 = base64.b64encode(image_bytes).decode()
        return await self._call(
            {"type": "image_base64", "image_base64": f"data:image/png;base64,{b64}"}, task
        )


class CohereEmbedClient(CachedHttpClientMixin):
    """Second fallback. embed-v4.0 defaults to 1536-dim — output_dimension
    must be set explicitly to 1024 or it won't fit chunks.embedding
    halfvec(1024) at all (not just a vector-space mismatch, a hard
    write failure)."""

    provider = PROVIDER_COHERE

    def __init__(self) -> None:
        self._api_key = os.environ.get("COHERE_API_KEY", "")

    async def _call(self, *, input_type: str, key: str, value: str) -> list[float]:
        client = self._client()
        response = await client.post(
            COHERE_EMBED_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": COHERE_EMBED_MODEL,
                "input_type": input_type,
                key: [value],
                "embedding_types": ["float"],
                "output_dimension": EMBEDDING_DIMENSIONS,
            },
        )
        if response.status_code >= 400:
            raise EmbedError("embed_call_failed", response.text)
        return response.json()["embeddings"]["float"][0]

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        # Cohere's own asymmetric distinction ("search_document" vs
        # "search_query") mapped from the shared task vocabulary, for
        # correctness even though this fallback is currently only ever
        # reached at ingest time (see VoyageEmbedClient.embed_text).
        input_type = "search_query" if task == "retrieval.query" else "search_document"
        return await self._call(input_type=input_type, key="texts", value=text)

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        b64 = base64.b64encode(image_bytes).decode()
        return await self._call(
            input_type="image", key="images", value=f"data:image/png;base64,{b64}"
        )


_client: EmbedClient = JinaEmbedClient()


def get_embed_client() -> EmbedClient:
    """The primary provider. Always what query-time embedding uses too
    (retrieve.py) — a query never falls back, since a fallback-provider
    query vector wouldn't be comparable to the (Jina-space) corpus."""
    return _client


def set_embed_client(client: EmbedClient) -> None:
    """Test seam — inject a fake embed client (deterministic, no network)."""
    global _client
    _client = client


def default_fallback_clients() -> list[EmbedClient]:
    return [VoyageEmbedClient(), CohereEmbedClient()]


_fallback_clients: list[EmbedClient] = default_fallback_clients()


def get_fallback_embed_clients() -> list[EmbedClient]:
    return _fallback_clients


def set_fallback_embed_clients(clients: list[EmbedClient]) -> None:
    """Test seam — override the fallback chain (e.g. to [] to disable it,
    or to fakes to test the fallback path deterministically)."""
    global _fallback_clients
    _fallback_clients = clients


class EmbedStorage(Protocol):
    async def get_document(self, *, user_jwt: str, document_id: str) -> dict[str, Any]: ...
    async def get_chunks(
        self, *, user_jwt: str, document_id: str
    ) -> list[dict[str, Any]]: ...
    async def download_original(self, *, user_jwt: str, path: str) -> bytes: ...
    async def get_checkpoint(self, *, user_jwt: str, document_id: str) -> dict[str, Any]: ...
    async def save_checkpoint(
        self, *, user_jwt: str, document_id: str, checkpoint: dict[str, Any]
    ) -> None: ...
    async def update_chunk_embedding(
        self, *, user_jwt: str, chunk_id: str, embedding: list[float]
    ) -> None: ...
    async def update_chunk_content(
        self, *, user_jwt: str, chunk_id: str, content: str
    ) -> None: ...
    async def mark_ready(self, *, user_jwt: str, document_id: str) -> None: ...
    async def mark_failed(self, *, user_jwt: str, document_id: str, error_code: str) -> None: ...
    async def set_document_embedding_provider(
        self, *, user_jwt: str, document_id: str, provider: str
    ) -> None: ...
    async def get_job_state(self, *, user_jwt: str, document_id: str) -> str | None:
        """None if no ingest_jobs row exists for this document at all."""
        ...
    async def reset_job_to_stage(self, *, user_jwt: str, document_id: str, state: str) -> None: ...


class SupabaseEmbedStorage(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {user_jwt}"}

    async def get_document(self, *, user_jwt: str, document_id: str) -> dict[str, Any]:
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/documents",
            headers=self._headers(user_jwt),
            params={"id": f"eq.{document_id}", "select": "*"},
        )
        rows = response.json()
        if not rows:
            raise EmbedError("document_not_found", document_id)
        return rows[0]

    async def get_chunks(self, *, user_jwt: str, document_id: str) -> list[dict[str, Any]]:
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/chunks",
            headers=self._headers(user_jwt),
            params={
                "document_id": f"eq.{document_id}",
                "select": "id,ordinal,content,meta",
                "order": "ordinal",
            },
        )
        return response.json()

    async def download_original(self, *, user_jwt: str, path: str) -> bytes:
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/storage/v1/object/originals/{path}",
            headers=self._headers(user_jwt),
        )
        if response.status_code >= 400:
            raise EmbedError("original_download_failed", path)
        return response.content

    async def get_checkpoint(self, *, user_jwt: str, document_id: str) -> dict[str, Any]:
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/ingest_jobs",
            headers=self._headers(user_jwt),
            params={"document_id": f"eq.{document_id}", "select": "checkpoint"},
        )
        rows = response.json()
        if not rows or not rows[0].get("checkpoint"):
            return {}
        return rows[0]["checkpoint"]

    async def save_checkpoint(
        self, *, user_jwt: str, document_id: str, checkpoint: dict[str, Any]
    ) -> None:
        client = self._client()
        await client.patch(
            f"{self._supabase_url}/rest/v1/ingest_jobs",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"document_id": f"eq.{document_id}"},
            json={"checkpoint": checkpoint},
        )

    async def update_chunk_embedding(
        self, *, user_jwt: str, chunk_id: str, embedding: list[float]
    ) -> None:
        client = self._client()
        response = await client.patch(
            f"{self._supabase_url}/rest/v1/chunks",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"id": f"eq.{chunk_id}"},
            json={"embedding": embedding},
        )
        if response.status_code >= 400:
            raise EmbedError("chunk_update_failed", chunk_id)

    async def update_chunk_content(
        self, *, user_jwt: str, chunk_id: str, content: str
    ) -> None:
        client = self._client()
        response = await client.patch(
            f"{self._supabase_url}/rest/v1/chunks",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"id": f"eq.{chunk_id}"},
            json={"content": content},
        )
        if response.status_code >= 400:
            raise EmbedError("chunk_update_failed", chunk_id)

    async def mark_ready(self, *, user_jwt: str, document_id: str) -> None:
        client = self._client()
        await client.patch(
            f"{self._supabase_url}/rest/v1/ingest_jobs",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"document_id": f"eq.{document_id}"},
            json={"state": "ready"},
        )
        await client.patch(
            f"{self._supabase_url}/rest/v1/documents",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"id": f"eq.{document_id}"},
            json={"status": "ready"},
        )

    async def mark_failed(self, *, user_jwt: str, document_id: str, error_code: str) -> None:
        client = self._client()
        await client.patch(
            f"{self._supabase_url}/rest/v1/ingest_jobs",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"document_id": f"eq.{document_id}"},
            json={"state": "failed", "last_error": error_code},
        )
        await client.patch(
            f"{self._supabase_url}/rest/v1/documents",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"id": f"eq.{document_id}"},
            json={"status": "failed"},
        )

    async def set_document_embedding_provider(
        self, *, user_jwt: str, document_id: str, provider: str
    ) -> None:
        client = self._client()
        await client.patch(
            f"{self._supabase_url}/rest/v1/documents",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"id": f"eq.{document_id}"},
            json={"embedding_provider": provider},
        )

    async def get_job_state(self, *, user_jwt: str, document_id: str) -> str | None:
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/ingest_jobs",
            headers=self._headers(user_jwt),
            params={"document_id": f"eq.{document_id}", "select": "state"},
        )
        rows = response.json()
        return rows[0]["state"] if rows else None

    async def reset_job_to_stage(self, *, user_jwt: str, document_id: str, state: str) -> None:
        client = self._client()
        await client.patch(
            f"{self._supabase_url}/rest/v1/ingest_jobs",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"document_id": f"eq.{document_id}"},
            json={"state": state, "last_error": None},
        )


_storage: EmbedStorage = SupabaseEmbedStorage()


def get_embed_storage() -> EmbedStorage:
    return _storage


def set_embed_storage(storage: EmbedStorage) -> None:
    """Test seam — inject a fake storage/DB client."""
    global _storage
    _storage = storage


def _is_image_document(mime: str) -> bool:
    return mime not in ("application/pdf", "text/plain", "text/markdown")


async def _embed_one(client: EmbedClient, *, is_image: bool, chunk: dict, original_bytes: bytes | None) -> list[float]:
    # Indexed content always embeds as "retrieval.passage" (both methods'
    # default) — the asymmetric "retrieval.query" adapter is only ever
    # for a live query (see retrieve.py), never for what gets stored.
    if is_image:
        tile = crop_tile(original_bytes, chunk["meta"]["bbox"])
        return await client.embed_image(tile)
    return await client.embed_text(chunk["content"])


async def run_embed_job(*, user_jwt: str, document_id: str) -> bool:
    """Returns True if every chunk got an embedding and the job advanced
    to `ready`, False if it failed partway (and was marked so — whatever
    was checkpointed stays done, a retry resumes from there).

    Provider fallback (Jina -> Voyage -> Cohere) only applies before this
    document has committed a single embedded chunk (locked_provider is
    None). Once locked_provider is known — either from a prior partial
    run via documents.embedding_provider, or from this run's own first
    success — every remaining chunk uses that one provider only; a
    failure there fails the job outright, exactly as before this fallback
    chain existed. This is what keeps a document's vectors in one
    provider's vector space for its whole life."""
    storage = get_embed_storage()

    document = await storage.get_document(user_jwt=user_jwt, document_id=document_id)
    is_image = _is_image_document(document["mime"])
    locked_provider = document.get("embedding_provider")

    chunks = await storage.get_chunks(user_jwt=user_jwt, document_id=document_id)
    checkpoint = await storage.get_checkpoint(user_jwt=user_jwt, document_id=document_id)
    last_done_ordinal = checkpoint.get("last_embedded_ordinal", -1)

    original_bytes: bytes | None = None
    image_caption: str | None = None
    if is_image:
        original_bytes = await storage.download_original(
            user_jwt=user_jwt, path=document["original_storage_path"]
        )
        # One caption for the whole document, reused for every tile chunk
        # below — same "caption the whole image once" reasoning as
        # retrieve/image_caption.py, and best-effort: None just leaves
        # content empty, exactly as before Stage 7.2.
        image_caption = await caption_image_bytes(original_bytes, mime_type=document["mime"])

    provider_clients = {get_embed_client().provider: get_embed_client()}
    for fallback_client in get_fallback_embed_clients():
        provider_clients[fallback_client.provider] = fallback_client

    async with INGEST_LOCK:
        for chunk in chunks:
            if chunk["ordinal"] <= last_done_ordinal:
                continue  # already embedded before a prior crash

            if locked_provider is not None:
                # Stage 7.6: locked_provider comes from documents.
                # embedding_provider — a prior run's own committed
                # state, or an operator-edited row — so it isn't
                # guaranteed to still have a matching entry in
                # provider_clients (e.g. a fallback provider's API key
                # removed from config after a document already locked
                # to it). A dict lookup here used to be a raw KeyError,
                # uncaught by `except EmbedError` below and propagating
                # all the way out of run_embed_job. Checked explicitly
                # so it fails the job gracefully instead.
                client = provider_clients.get(locked_provider)
                if client is None:
                    await storage.mark_failed(
                        user_jwt=user_jwt,
                        document_id=document_id,
                        error_code="provider_not_configured",
                    )
                    return False
                try:
                    embedding = await _embed_one(
                        client,
                        is_image=is_image,
                        chunk=chunk,
                        original_bytes=original_bytes,
                    )
                except EmbedError as exc:
                    await storage.mark_failed(
                        user_jwt=user_jwt, document_id=document_id, error_code=exc.code
                    )
                    return False
            else:
                embedding = None
                last_error_code = "embed_call_failed"
                for candidate in [get_embed_client(), *get_fallback_embed_clients()]:
                    try:
                        embedding = await _embed_one(
                            candidate,
                            is_image=is_image,
                            chunk=chunk,
                            original_bytes=original_bytes,
                        )
                        locked_provider = candidate.provider
                        await storage.set_document_embedding_provider(
                            user_jwt=user_jwt,
                            document_id=document_id,
                            provider=locked_provider,
                        )
                        break
                    except EmbedError as exc:
                        last_error_code = exc.code
                        continue
                if embedding is None:
                    await storage.mark_failed(
                        user_jwt=user_jwt, document_id=document_id, error_code=last_error_code
                    )
                    return False

            await storage.update_chunk_embedding(
                user_jwt=user_jwt, chunk_id=chunk["id"], embedding=embedding
            )
            if image_caption and not chunk["content"]:
                await storage.update_chunk_content(
                    user_jwt=user_jwt, chunk_id=chunk["id"], content=image_caption
                )
            await storage.save_checkpoint(
                user_jwt=user_jwt,
                document_id=document_id,
                checkpoint={"last_embedded_ordinal": chunk["ordinal"]},
            )

    await storage.mark_ready(user_jwt=user_jwt, document_id=document_id)
    return True


class RetryError(Exception):
    """Raised when a document's failed job isn't safely retryable yet."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


async def check_retry_eligible(*, user_jwt: str, document_id: str) -> str:
    """Checked synchronously by the retry-ingest route before scheduling
    a background task (same request/response shape as upload-confirm).
    Raises RetryError if not eligible; otherwise resets the job to the
    stage it should resume from and returns that stage name, so the
    route knows which pipeline function to schedule.

    Two eligible cases:
    - Chunks already exist for this document ("embedding" failed, since
      extract.py only ever produces chunks right before mark_extracted).
      run_embed_job's checkpoint + provider-lock make it safe to re-call
      at any point — resets to `embedding`.
    - No chunks exist yet (Stage 7.5 — normalize or extract failed).
      Safe to restart the whole pre-embed part of the pipeline from
      scratch: extract.py's insert_chunks is one all-or-nothing bulk
      insert called exactly once, right at the end of run_extract_job,
      so by construction either every chunk for a document exists or
      none do — there is no partial-chunks state a restart could ever
      duplicate into. normalize.py is also safely re-runnable: it
      overwrites the same `indexed` storage path and re-patches the
      same `documents` row, never inserts a row. Resets to
      `normalizing` — or `extracting` for a captured thought (Stage
      5.5's source == "capture" documents have no normalize stage at
      all, per _run_capture_pipeline).
    """
    storage = get_embed_storage()

    job_state = await storage.get_job_state(user_jwt=user_jwt, document_id=document_id)
    if job_state is None:
        raise RetryError("not_found", "No ingest job found for this document")
    if job_state != "failed":
        raise RetryError(
            "not_retryable", f"Job is not in a failed state (state={job_state})"
        )

    chunks = await storage.get_chunks(user_jwt=user_jwt, document_id=document_id)
    if chunks:
        await storage.reset_job_to_stage(
            user_jwt=user_jwt, document_id=document_id, state="embedding"
        )
        return "embedding"

    document = await storage.get_document(user_jwt=user_jwt, document_id=document_id)
    resume_stage = "extracting" if document.get("source") == "capture" else "normalizing"
    await storage.reset_job_to_stage(
        user_jwt=user_jwt, document_id=document_id, state=resume_stage
    )
    return resume_stage
