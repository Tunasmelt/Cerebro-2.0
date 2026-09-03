"""Retry for failed ingest jobs (embed-stage retry added after Stage
1.4; normalize/extract-stage retry added in Stage 7.5, closing the gap
this file's own docstring used to flag as intentionally out of scope).

check_retry_eligible now resumes from wherever it's actually safe to
resume:
- Chunks already exist for this document -> only embed failed (extract
  only ever produces chunks in one all-or-nothing bulk insert right
  before mark_extracted) -> reset to `embedding`, run_embed_job's own
  checkpoint/provider-lock does the rest.
- No chunks exist yet -> normalize and/or extract is what failed ->
  safe to restart the whole pre-embed pipeline from scratch, since
  there is no partial-chunks state to ever duplicate into -> reset to
  `normalizing` (or `extracting` for a captured thought, which has no
  normalize stage at all).
"""
import pytest

from app.ingest import embed as embed_module
from app.ingest.embed import RetryError, check_retry_eligible


class _FakeRetryStorage:
    def __init__(self, *, job_state: str | None, chunks: list[dict], document: dict | None = None):
        self.job_state = job_state
        self.chunks = chunks
        self.document = document or {"id": "doc", "source": "upload"}
        self.reset_calls: list[str] = []

    async def get_job_state(self, *, user_jwt, document_id):
        return self.job_state

    async def get_chunks(self, *, user_jwt, document_id):
        return self.chunks

    async def get_document(self, *, user_jwt, document_id):
        return self.document

    async def reset_job_to_stage(self, *, user_jwt, document_id, state):
        self.reset_calls.append(state)
        self.job_state = state


@pytest.fixture(autouse=True)
def _reset():
    yield
    embed_module.set_embed_storage(embed_module.SupabaseEmbedStorage())


@pytest.mark.asyncio
async def test_eligible_when_failed_with_chunks_already_extracted():
    storage = _FakeRetryStorage(job_state="failed", chunks=[{"id": "c0"}])
    embed_module.set_embed_storage(storage)

    resume_stage = await check_retry_eligible(user_jwt="t", document_id="doc-1")

    assert resume_stage == "embedding"
    assert storage.reset_calls == ["embedding"]
    assert storage.job_state == "embedding"


@pytest.mark.asyncio
async def test_not_found_when_no_job_exists():
    storage = _FakeRetryStorage(job_state=None, chunks=[])
    embed_module.set_embed_storage(storage)

    with pytest.raises(RetryError) as exc_info:
        await check_retry_eligible(user_jwt="t", document_id="doc-2")

    assert exc_info.value.code == "not_found"
    assert storage.reset_calls == []


@pytest.mark.asyncio
async def test_not_retryable_when_job_is_not_failed():
    storage = _FakeRetryStorage(job_state="embedding", chunks=[{"id": "c0"}])
    embed_module.set_embed_storage(storage)

    with pytest.raises(RetryError) as exc_info:
        await check_retry_eligible(user_jwt="t", document_id="doc-3")

    assert exc_info.value.code == "not_retryable"
    assert storage.reset_calls == []


@pytest.mark.asyncio
async def test_failed_before_any_chunk_extracted_resumes_from_normalizing():
    # Stage 7.5: this used to be rejected as not_retryable. Now — no
    # chunks exist, so normalize/extract is what failed, and it's safe
    # to restart the whole pre-embed pipeline.
    storage = _FakeRetryStorage(
        job_state="failed", chunks=[], document={"id": "doc-4", "source": "upload"}
    )
    embed_module.set_embed_storage(storage)

    resume_stage = await check_retry_eligible(user_jwt="t", document_id="doc-4")

    assert resume_stage == "normalizing"
    assert storage.reset_calls == ["normalizing"]


@pytest.mark.asyncio
async def test_captured_thought_with_no_chunks_resumes_from_extracting():
    # A capture (Stage 5.5) has no normalize stage at all — its retry
    # must resume from extracting, not normalizing.
    storage = _FakeRetryStorage(
        job_state="failed", chunks=[], document={"id": "doc-5", "source": "capture"}
    )
    embed_module.set_embed_storage(storage)

    resume_stage = await check_retry_eligible(user_jwt="t", document_id="doc-5")

    assert resume_stage == "extracting"
    assert storage.reset_calls == ["extracting"]
