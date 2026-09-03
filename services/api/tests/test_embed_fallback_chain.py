"""Embedding provider fallback (Jina -> Voyage -> Cohere), added after
Stage 1.4 as new scope, not part of its original exit criteria.

Different providers produce incompatible vector spaces even at the same
dimension, so the fallback must be whole-job-before-first-chunk only:
once a document has committed a single chunk with a provider, it's
locked to that provider for life — no mid-job switching. See embed.py's
module docstring for the full reasoning.
"""
import pytest

from app.ingest import embed as embed_module
from app.ingest.embed import EmbedError, run_embed_job

MIME = "text/plain"


class _FakeClient:
    def __init__(self, provider: str, *, always_fails: bool = False):
        self.provider = provider
        self.always_fails = always_fails
        self.text_calls: list[str] = []

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        self.text_calls.append(text)
        if self.always_fails:
            raise EmbedError(f"{self.provider}_failed", f"{self.provider} is down")
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        raise NotImplementedError


class _FakeStorage:
    def __init__(self, *, chunks: list[dict], embedding_provider: str | None = None):
        self.chunks = chunks
        self.checkpoint: dict = {}
        self.embeddings: dict[str, list[float]] = {}
        self.marked_ready = False
        self.marked_failed = None
        self.embedding_provider = embedding_provider

    async def get_document(self, *, user_jwt, document_id):
        doc = {
            "id": document_id,
            "user_id": "u",
            "mime": MIME,
            "original_storage_path": "u/doc/original.bin",
        }
        if self.embedding_provider is not None:
            doc["embedding_provider"] = self.embedding_provider
        return doc

    async def get_chunks(self, *, user_jwt, document_id):
        return self.chunks

    async def download_original(self, *, user_jwt, path):
        return b""

    async def get_checkpoint(self, *, user_jwt, document_id):
        return self.checkpoint

    async def save_checkpoint(self, *, user_jwt, document_id, checkpoint):
        self.checkpoint = checkpoint

    async def update_chunk_embedding(self, *, user_jwt, chunk_id, embedding):
        self.embeddings[chunk_id] = embedding

    async def mark_ready(self, *, user_jwt, document_id):
        self.marked_ready = True

    async def mark_failed(self, *, user_jwt, document_id, error_code):
        self.marked_failed = error_code

    async def set_document_embedding_provider(self, *, user_jwt, document_id, provider):
        self.embedding_provider = provider


def _chunks(n: int) -> list[dict]:
    return [
        {"id": f"chunk-{i}", "ordinal": i, "content": f"text {i}", "meta": {}}
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _reset():
    yield
    embed_module.set_embed_client(embed_module.JinaEmbedClient())
    embed_module.set_embed_storage(embed_module.SupabaseEmbedStorage())
    embed_module.set_fallback_embed_clients(embed_module.default_fallback_clients())


@pytest.mark.asyncio
async def test_falls_back_to_second_provider_when_first_fails_before_any_chunk():
    jina = _FakeClient("jina", always_fails=True)
    voyage = _FakeClient("voyage")
    cohere = _FakeClient("cohere")
    storage = _FakeStorage(chunks=_chunks(2))
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(jina)
    embed_module.set_fallback_embed_clients([voyage, cohere])

    result = await run_embed_job(user_jwt="t", document_id="doc-1")

    assert result is True
    assert jina.text_calls == ["text 0"]  # tried once, failed, never touched again
    assert voyage.text_calls == ["text 0", "text 1"]  # locked in after success
    assert cohere.text_calls == []
    assert storage.embedding_provider == "voyage"
    assert storage.marked_ready is True


@pytest.mark.asyncio
async def test_falls_through_to_third_provider():
    jina = _FakeClient("jina", always_fails=True)
    voyage = _FakeClient("voyage", always_fails=True)
    cohere = _FakeClient("cohere")
    storage = _FakeStorage(chunks=_chunks(1))
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(jina)
    embed_module.set_fallback_embed_clients([voyage, cohere])

    result = await run_embed_job(user_jwt="t", document_id="doc-2")

    assert result is True
    assert storage.embedding_provider == "cohere"


@pytest.mark.asyncio
async def test_job_fails_if_every_provider_fails_on_the_first_chunk():
    jina = _FakeClient("jina", always_fails=True)
    voyage = _FakeClient("voyage", always_fails=True)
    cohere = _FakeClient("cohere", always_fails=True)
    storage = _FakeStorage(chunks=_chunks(1))
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(jina)
    embed_module.set_fallback_embed_clients([voyage, cohere])

    result = await run_embed_job(user_jwt="t", document_id="doc-3")

    assert result is False
    assert storage.marked_ready is False
    assert storage.marked_failed == "cohere_failed"  # last provider tried
    assert storage.embedding_provider is None  # never locked, nothing committed


@pytest.mark.asyncio
async def test_no_fallback_once_a_provider_is_already_locked_from_a_prior_partial_run():
    # Simulates resuming a job whose document already has
    # embedding_provider="voyage" from a previous run (one chunk
    # committed, then crashed). Jina "recovering" must NOT be used —
    # the document stays locked to voyage even if voyage now fails too.
    jina = _FakeClient("jina")  # would succeed if tried — must not be tried
    voyage = _FakeClient("voyage", always_fails=True)
    storage = _FakeStorage(chunks=_chunks(2), embedding_provider="voyage")
    storage.checkpoint = {"last_embedded_ordinal": 0}  # chunk 0 already done
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(jina)
    embed_module.set_fallback_embed_clients([voyage])

    result = await run_embed_job(user_jwt="t", document_id="doc-4")

    assert result is False
    assert storage.marked_failed == "voyage_failed"
    assert jina.text_calls == []  # locked provider — no fallback attempted


@pytest.mark.asyncio
async def test_no_fallback_triggered_when_primary_succeeds_immediately():
    # Regression guard: an empty/non-empty fallback list must not change
    # behavior at all when the primary provider just works.
    jina = _FakeClient("jina")
    voyage = _FakeClient("voyage")
    storage = _FakeStorage(chunks=_chunks(3))
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(jina)
    embed_module.set_fallback_embed_clients([voyage])

    result = await run_embed_job(user_jwt="t", document_id="doc-5")

    assert result is True
    assert voyage.text_calls == []
    assert storage.embedding_provider == "jina"


@pytest.mark.asyncio
async def test_locked_provider_with_no_matching_client_fails_gracefully_not_a_keyerror():
    # Stage 7.6 regression: documents.embedding_provider names a
    # provider ("cohere") that isn't in provider_clients at all (e.g. a
    # fallback client removed from config after this document already
    # locked to it) — used to be a raw, uncaught KeyError.
    jina = _FakeClient("jina")  # must not be tried — provider is locked
    storage = _FakeStorage(chunks=_chunks(1), embedding_provider="cohere")
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(jina)
    embed_module.set_fallback_embed_clients([])  # no cohere client configured

    result = await run_embed_job(user_jwt="t", document_id="doc-6")

    assert result is False
    assert storage.marked_failed == "provider_not_configured"
    assert jina.text_calls == []
