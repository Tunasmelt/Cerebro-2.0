"""Retry for failed embed-stage ingest jobs (added after Stage 1.4, at
the user's request, once the checkpoint/provider-lock work made clear
that resuming a failed embed job was already safe — the missing piece
was that nothing ever called run_embed_job a second time).

Deliberately scoped to embed-stage failures only: normalize.py has no
skip-if-already-done check, and extract.py's re-run behavior on an
already-extracted document is unverified, so retrying by blindly
re-running the whole pipeline risks duplicate chunk rows. "Chunks
already exist" is the proxy for "extract completed, so embed is what
actually failed" — anything earlier is rejected, not silently attempted.
"""
import pytest

from app.ingest import embed as embed_module
from app.ingest.embed import RetryError, check_retry_eligible


class _FakeRetryStorage:
    def __init__(self, *, job_state: str | None, chunks: list[dict]):
        self.job_state = job_state
        self.chunks = chunks
        self.reset_called = False

    async def get_job_state(self, *, user_jwt, document_id):
        return self.job_state

    async def get_chunks(self, *, user_jwt, document_id):
        return self.chunks

    async def reset_job_to_embedding(self, *, user_jwt, document_id):
        self.reset_called = True
        self.job_state = "embedding"


@pytest.fixture(autouse=True)
def _reset():
    yield
    embed_module.set_embed_storage(embed_module.SupabaseEmbedStorage())


@pytest.mark.asyncio
async def test_eligible_when_failed_with_chunks_already_extracted():
    storage = _FakeRetryStorage(job_state="failed", chunks=[{"id": "c0"}])
    embed_module.set_embed_storage(storage)

    await check_retry_eligible(user_jwt="t", document_id="doc-1")

    assert storage.reset_called is True
    assert storage.job_state == "embedding"


@pytest.mark.asyncio
async def test_not_found_when_no_job_exists():
    storage = _FakeRetryStorage(job_state=None, chunks=[])
    embed_module.set_embed_storage(storage)

    with pytest.raises(RetryError) as exc_info:
        await check_retry_eligible(user_jwt="t", document_id="doc-2")

    assert exc_info.value.code == "not_found"
    assert storage.reset_called is False


@pytest.mark.asyncio
async def test_not_retryable_when_job_is_not_failed():
    storage = _FakeRetryStorage(job_state="embedding", chunks=[{"id": "c0"}])
    embed_module.set_embed_storage(storage)

    with pytest.raises(RetryError) as exc_info:
        await check_retry_eligible(user_jwt="t", document_id="doc-3")

    assert exc_info.value.code == "not_retryable"
    assert storage.reset_called is False


@pytest.mark.asyncio
async def test_not_retryable_when_failed_before_any_chunk_extracted():
    # Failed during normalize/extract — not safe to auto-retry yet.
    storage = _FakeRetryStorage(job_state="failed", chunks=[])
    embed_module.set_embed_storage(storage)

    with pytest.raises(RetryError) as exc_info:
        await check_retry_eligible(user_jwt="t", document_id="doc-4")

    assert exc_info.value.code == "not_retryable"
    assert storage.reset_called is False
