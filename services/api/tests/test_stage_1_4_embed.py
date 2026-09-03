"""Stage 1.4 — embed & job state machine.

Exit criteria: chunks get embeddings; ingest_jobs tracks state through
uploading -> normalizing -> extracting -> embedding -> ready, with
checkpoints allowing resume after a mid-job crash.

Tests: killing the process mid-embedding and restarting resumes from the
checkpoint, not from scratch. Ingest concurrency confirmed at 1 under
load, verified by timing.

Since a literal OS-process kill isn't practical or deterministic in an
automated suite, "crash mid-job" is simulated via fault injection in the
embed client (same technique the corrupt-file tests use elsewhere) —
the checkpoint mechanism itself is real, only the trigger is simulated.
Live-verified against the real Jina API and Supabase separately (see
conversation record: response shape, embedding dimensions, and PostgREST
accepting a plain JSON array for the halfvec column were all confirmed
against the live services before writing this code).
"""
import asyncio
import io
import time

import pytest
from PIL import Image

from app.ingest import embed as embed_module
from app.ingest import normalize as normalize_module
from app.ingest.embed import EmbedError, crop_tile, run_embed_job

TEXT_DOC_MIME = "text/plain"
IMAGE_DOC_MIME = "image/jpeg"


def _make_image_bytes(size=(500, 400)) -> bytes:
    img = Image.new("RGB", size, color=(10, 20, 30))
    out = io.BytesIO()
    img.save(out, format="JPEG")
    return out.getvalue()


class _FakeEmbedClient:
    provider = "jina"

    def __init__(self, *, fail_after: int | None = None):
        self.text_calls: list[str] = []
        self.image_calls: list[bytes] = []
        self.fail_after = fail_after  # raise on the (fail_after+1)th call

    def _maybe_fail(self):
        total_calls = len(self.text_calls) + len(self.image_calls)
        if self.fail_after is not None and total_calls > self.fail_after:
            raise EmbedError("simulated_crash", "injected failure")

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        self.text_calls.append(text)
        self._maybe_fail()
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        self.image_calls.append(image_bytes)
        self._maybe_fail()
        return [0.2] * 1024


class _FakeEmbedStorage:
    def __init__(self, *, mime: str, chunks: list[dict], original_content: bytes = b""):
        self.mime = mime
        self.chunks = chunks
        self.original_content = original_content
        self.checkpoint: dict = {}
        self.embeddings: dict[str, list[float]] = {}
        self.marked_ready = False
        self.marked_failed = None
        self.embedding_provider = None

    async def get_document(self, *, user_jwt, document_id):
        return {
            "id": document_id,
            "user_id": "11111111-1111-1111-1111-111111111111",
            "mime": self.mime,
            "original_storage_path": "u/doc/original.bin",
        }

    async def get_chunks(self, *, user_jwt, document_id):
        return self.chunks

    async def download_original(self, *, user_jwt, path):
        return self.original_content

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


@pytest.fixture(autouse=True)
def _reset():
    # These pre-existing Stage 1.4 tests predate the Voyage/Cohere
    # fallback chain and assert immediate mark_failed on the fake
    # client's failure — an empty fallback list keeps that exact
    # behavior; the fallback path itself is covered in
    # test_embed_fallback_chain.py.
    embed_module.set_fallback_embed_clients([])
    yield
    embed_module.set_embed_client(embed_module.JinaEmbedClient())
    embed_module.set_embed_storage(embed_module.SupabaseEmbedStorage())
    embed_module.set_fallback_embed_clients(embed_module.default_fallback_clients())


def _text_chunks(n: int) -> list[dict]:
    return [
        {"id": f"chunk-{i}", "ordinal": i, "content": f"chunk text {i}", "meta": {}}
        for i in range(n)
    ]


# --- crop_tile -----------------------------------------------------------------


def test_crop_tile_produces_correct_dimensions():
    original = _make_image_bytes((500, 400))
    tile = crop_tile(original, [0, 0, 250, 200])
    tile_img = Image.open(io.BytesIO(tile))
    assert tile_img.size == (250, 200)


# --- run_embed_job happy paths --------------------------------------------------


@pytest.mark.asyncio
async def test_run_embed_job_text_embeds_every_chunk():
    storage = _FakeEmbedStorage(mime=TEXT_DOC_MIME, chunks=_text_chunks(3))
    client = _FakeEmbedClient()
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(client)

    result = await run_embed_job(user_jwt="t", document_id="doc-1")

    assert result is True
    assert client.text_calls == ["chunk text 0", "chunk text 1", "chunk text 2"]
    assert len(storage.embeddings) == 3
    assert storage.marked_ready is True
    assert storage.checkpoint == {"last_embedded_ordinal": 2}


@pytest.mark.asyncio
async def test_run_embed_job_markdown_embeds_as_text_not_image():
    """_is_image_document only excludes application/pdf and text/plain —
    text/markdown had to be added there too, or a .md upload would
    silently misroute into the image-tile embedding path and crash on
    the missing original_bytes/bbox it never has."""
    storage = _FakeEmbedStorage(mime="text/markdown", chunks=_text_chunks(2))
    client = _FakeEmbedClient()
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(client)

    result = await run_embed_job(user_jwt="t", document_id="doc-md")

    assert result is True
    assert client.text_calls == ["chunk text 0", "chunk text 1"]
    assert client.image_calls == []
    assert storage.marked_ready is True


@pytest.mark.asyncio
async def test_run_embed_job_image_crops_tiles_and_embeds_images():
    original = _make_image_bytes((500, 400))
    chunks = [
        {"id": "c0", "ordinal": 0, "content": "", "meta": {"bbox": [0, 0, 250, 400]}},
        {"id": "c1", "ordinal": 1, "content": "", "meta": {"bbox": [250, 0, 500, 400]}},
    ]
    storage = _FakeEmbedStorage(mime=IMAGE_DOC_MIME, chunks=chunks, original_content=original)
    client = _FakeEmbedClient()
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(client)

    result = await run_embed_job(user_jwt="t", document_id="doc-2")

    assert result is True
    assert len(client.image_calls) == 2
    assert client.text_calls == []
    for tile_bytes in client.image_calls:
        tile_img = Image.open(io.BytesIO(tile_bytes))
        assert tile_img.size == (250, 400)


# --- checkpoint / resume (the exit criteria's actual point) ------------------


@pytest.mark.asyncio
async def test_resuming_skips_chunks_already_past_the_checkpoint():
    storage = _FakeEmbedStorage(mime=TEXT_DOC_MIME, chunks=_text_chunks(4))
    storage.checkpoint = {"last_embedded_ordinal": 1}  # chunks 0,1 already done
    client = _FakeEmbedClient()
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(client)

    result = await run_embed_job(user_jwt="t", document_id="doc-3")

    assert result is True
    # Only ordinals 2 and 3 should have been (re-)embedded.
    assert client.text_calls == ["chunk text 2", "chunk text 3"]


@pytest.mark.asyncio
async def test_crash_mid_job_then_restart_resumes_from_checkpoint_not_from_scratch():
    chunks = _text_chunks(4)
    storage = _FakeEmbedStorage(mime=TEXT_DOC_MIME, chunks=chunks)
    # "Process crashes" after the 2nd chunk's embed call succeeds.
    crashing_client = _FakeEmbedClient(fail_after=2)
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(crashing_client)

    first_attempt = await run_embed_job(user_jwt="t", document_id="doc-4")

    assert first_attempt is False
    assert storage.marked_failed == "simulated_crash"
    assert storage.checkpoint == {"last_embedded_ordinal": 1}  # 0,1 done; 2 failed
    assert len(storage.embeddings) == 2

    # "Restart the process" — fresh client (no fail_after), same storage
    # instance (as it would be, since the checkpoint lives in the DB, not
    # in-process memory).
    fresh_client = _FakeEmbedClient()
    embed_module.set_embed_client(fresh_client)

    second_attempt = await run_embed_job(user_jwt="t", document_id="doc-4")

    assert second_attempt is True
    assert storage.marked_ready is True
    # The resumed run must NOT have re-embedded chunks 0 or 1.
    assert fresh_client.text_calls == ["chunk text 2", "chunk text 3"]
    assert len(storage.embeddings) == 4


@pytest.mark.asyncio
async def test_failed_job_does_not_mark_ready():
    storage = _FakeEmbedStorage(mime=TEXT_DOC_MIME, chunks=_text_chunks(2))
    client = _FakeEmbedClient(fail_after=0)
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(client)

    result = await run_embed_job(user_jwt="t", document_id="doc-5")

    assert result is False
    assert storage.marked_ready is False
    assert storage.marked_failed == "simulated_crash"


# --- concurrency = 1, across the WHOLE pipeline not just within one stage ----


@pytest.mark.asyncio
async def test_ingest_concurrency_is_one_across_normalize_and_embed():
    # Regression test for the gap fixed in this stage: Stage 1.2 originally
    # had its own private lock, so normalizing document A and embedding
    # document B could run concurrently — violating CLAUDE.md's
    # "concurrency=1 on the ingest worker" (singular: the whole pipeline).
    order: list[str] = []

    class _SlowNormalizeStorage:
        async def get_document(self, *, user_jwt, document_id):
            return {"user_id": "u", "mime": "text/plain", "original_storage_path": "p"}

        async def download_original(self, *, user_jwt, path):
            order.append("normalize-start")
            await asyncio.sleep(0.05)
            order.append("normalize-end")
            return b"hello"

        async def upload_indexed(self, **kwargs):
            return "indexed/p"

        async def mark_normalized(self, **kwargs):
            pass

        async def mark_failed(self, **kwargs):
            pass

    storage = _FakeEmbedStorage(mime=TEXT_DOC_MIME, chunks=_text_chunks(1))

    class _SlowFakeEmbedClient(_FakeEmbedClient):
        async def embed_text(self, text, task: str = "retrieval.passage"):
            order.append("embed-start")
            await asyncio.sleep(0.05)
            order.append("embed-end")
            return [0.1] * 1024

    normalize_module.set_normalize_storage(_SlowNormalizeStorage())
    embed_module.set_embed_storage(storage)
    embed_module.set_embed_client(_SlowFakeEmbedClient())

    start = time.monotonic()
    await asyncio.gather(
        normalize_module.run_normalize_job(user_jwt="t", document_id="doc-a"),
        run_embed_job(user_jwt="t", document_id="doc-b"),
    )
    elapsed = time.monotonic() - start

    # Serialized: total time is roughly the sum, not the max, of the two
    # 0.05s steps — and no "-start" appears before the previous "-end".
    assert elapsed >= 0.09, f"expected serialized (~0.1s), ran in {elapsed}s — looks concurrent"
    ends = {i for i, e in enumerate(order) if e.endswith("-end")}
    starts = {i for i, e in enumerate(order) if e.endswith("-start")}
    first_end = min(ends)
    assert all(s < first_end or s > first_end for s in starts)  # sanity
    assert len([s for s in starts if s < first_end]) == 1, (
        f"more than one stage's heavy step started before the first finished: {order}"
    )

    normalize_module.set_normalize_storage(normalize_module.SupabaseNormalizeStorage())
