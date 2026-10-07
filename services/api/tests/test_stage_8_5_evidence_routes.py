from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.core import evidence_storage as storage_module
from app.core.evidence_storage import EvidenceError
from app.routes.documents import get_chunk_evidence, reindex_layout


class FakeStorage:
    def __init__(self, *, evidence=None, error=None, queue="queued"):
        self.evidence = evidence
        self.error = error
        self.queue = queue

    async def get_evidence(self, **_kwargs):
        if self.error:
            raise self.error
        return self.evidence

    async def queue_reindex(self, **_kwargs):
        if self.error:
            raise self.error
        return self.queue


def request():
    return SimpleNamespace(state=SimpleNamespace(user_jwt="jwt", user={"sub": "user"}))


@pytest.fixture(autouse=True)
def reset_storage():
    yield
    storage_module.set_evidence_storage(storage_module.SupabaseEvidenceStorage())


@pytest.mark.asyncio
async def test_evidence_route_returns_exact_region_payload():
    expected = {"chunk_id": "c", "region": {"bbox": [0, 0, 1, 1]}, "render_url": "signed"}
    storage_module.set_evidence_storage(FakeStorage(evidence=expected))
    response = await get_chunk_evidence(request(), "c")
    assert response.status_code == 200
    assert response.body


@pytest.mark.asyncio
@pytest.mark.parametrize("code,status", [("not_found", 404), ("document_sealed", 423)])
async def test_evidence_route_hides_foreign_and_locks_sealed(code, status):
    storage_module.set_evidence_storage(FakeStorage(error=EvidenceError(code, code)))
    response = await get_chunk_evidence(request(), "c")
    assert response.status_code == status


@pytest.mark.asyncio
async def test_reindex_is_idempotently_queued():
    storage_module.set_evidence_storage(FakeStorage(queue="already_queued"))
    response = await reindex_layout(request(), "doc", BackgroundTasks())
    assert response.status_code == 202
    assert b"already_queued" in response.body
