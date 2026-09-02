"""Stage 3.4 — metadata-only search filtering.

Exit criteria: sealed content never enters retrieval results; only
metadata is searchable while sealed.
Tests required: a query using exact phrasing from sealed content returns
zero matches on that content pre-unlock; returns it post-unlock.

Two layers are covered:
1. The RPC-level defense-in-depth filter (static check on the migration
   SQL — sealed chunks are already absent from `chunks` after Stage
   3.3's seal_document deletes them, so this is belt-and-suspenders, not
   the primary mechanism; verified the same static way as Stage 3.1's
   schema test since there's no live Postgres in CI).
2. retrieve()'s actual pre/post-unlock behavior — a fake base
   RetrieveStorage returns nothing (mirroring "sealed content isn't in
   `chunks` at all"), and a fake SealedStorage backs the post-unlock
   exact-phrase path.
"""
from pathlib import Path

import pytest

from app.core import sealed_storage as sealed_storage_module
from app.core.sealed_storage import SealedStorageError
from app.ingest import embed as embed_module
from app.retrieve import retrieve as retrieve_module
from app.retrieve.retrieve import UnlockedDocument, retrieve

MIGRATIONS_DIR = Path(__file__).parents[3] / "supabase" / "migrations"


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )


# --- Static migration check --------------------------------------------------


def test_retrieval_rpcs_exclude_sealed_documents():
    matches = list(MIGRATIONS_DIR.glob("*seal_retrieval_filter*.sql"))
    assert len(matches) == 1, "expected exactly one seal-retrieval-filter migration"
    sql = _strip_sql_comments(matches[0].read_text()).lower()

    assert sql.count("documents.status <> 'sealed'") == 2, (
        "expected the sealed-status exclusion in both "
        "match_chunks_vector and match_chunks_fts"
    )
    assert "join documents on documents.id = chunks.document_id" in sql


# --- retrieve() pre/post-unlock behavior -------------------------------------


class _FakeEmbedClient:
    provider = "jina"

    async def embed_text(self, text: str, task: str = "retrieval.passage") -> list[float]:
        return [0.1] * 1024

    async def embed_image(self, image_bytes: bytes, task: str = "retrieval.passage") -> list[float]:
        raise NotImplementedError


class _EmptyRetrieveStorage:
    """Stands in for the real Postgres state after sealing: the base
    vector/FTS search paths return nothing, because sealed chunks were
    deleted from `chunks` entirely (Stage 3.3)."""

    async def vector_search(self, *, user_jwt, query_embedding, match_count, primary_provider):
        return []

    async def fts_search(self, *, user_jwt, query_text, match_count):
        return []


class _FakeSealedStorage:
    def __init__(self, *, chunks_by_document: dict[str, list[dict]] | None = None):
        self.chunks_by_document = chunks_by_document or {}
        self.raise_for_document: dict[str, SealedStorageError] = {}

    async def seal_document(self, *, user_jwt, user_id, document_id, chunks):
        raise NotImplementedError

    async def create_unlock_claim(self, *, user_jwt, user_id, document_id, key_b64):
        raise NotImplementedError

    async def unseal_document(self, *, user_jwt, user_id, document_id, claim_id, key_b64):
        if document_id in self.raise_for_document:
            raise self.raise_for_document[document_id]
        return self.chunks_by_document.get(document_id, [])


@pytest.fixture(autouse=True)
def _reset():
    yield
    embed_module.set_embed_client(embed_module.JinaEmbedClient())
    retrieve_module.set_rerank_client(retrieve_module.CohereRerankClient())
    retrieve_module.set_retrieve_storage(retrieve_module.SupabaseRetrieveStorage())
    sealed_storage_module.set_sealed_storage(sealed_storage_module.SupabaseSealedStorage())


@pytest.mark.asyncio
async def test_exact_sealed_phrase_returns_zero_matches_pre_unlock():
    """Required test: a query using exact phrasing from sealed content
    returns zero matches on that content pre-unlock."""
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_retrieve_storage(_EmptyRetrieveStorage())
    sealed_storage_module.set_sealed_storage(_FakeSealedStorage())

    results = await retrieve(
        user_jwt="t", query="the secret merger closes in march", unlocked=None
    )

    assert results == []


@pytest.mark.asyncio
async def test_exact_sealed_phrase_returns_it_post_unlock():
    """Required test: the same query returns the sealed content once a
    valid unlock claim + key are supplied for that document."""
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_retrieve_storage(_EmptyRetrieveStorage())
    sealed_storage_module.set_sealed_storage(
        _FakeSealedStorage(
            chunks_by_document={
                "doc-1": [
                    {"ordinal": 0, "content": "the secret merger closes in march"}
                ]
            }
        )
    )

    results = await retrieve(
        user_jwt="t",
        user_id="user-1",
        query="the secret merger closes in march",
        unlocked=[UnlockedDocument(document_id="doc-1", claim_id="claim-1", key_b64="a2V5")],
    )

    assert len(results) == 1
    assert results[0].document_id == "doc-1"
    assert results[0].content == "the secret merger closes in march"


@pytest.mark.asyncio
async def test_unlocked_document_with_no_matching_phrase_yields_nothing():
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_retrieve_storage(_EmptyRetrieveStorage())
    sealed_storage_module.set_sealed_storage(
        _FakeSealedStorage(
            chunks_by_document={"doc-1": [{"ordinal": 0, "content": "unrelated content"}]}
        )
    )

    results = await retrieve(
        user_jwt="t",
        user_id="user-1",
        query="the secret merger closes in march",
        unlocked=[UnlockedDocument(document_id="doc-1", claim_id="claim-1", key_b64="a2V5")],
    )

    assert results == []


@pytest.mark.asyncio
async def test_invalid_claim_degrades_to_no_matches_instead_of_crashing():
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_retrieve_storage(_EmptyRetrieveStorage())
    fake_sealed = _FakeSealedStorage()
    fake_sealed.raise_for_document["doc-1"] = SealedStorageError("claim_expired", "expired")
    sealed_storage_module.set_sealed_storage(fake_sealed)

    results = await retrieve(
        user_jwt="t",
        user_id="user-1",
        query="the secret merger closes in march",
        unlocked=[UnlockedDocument(document_id="doc-1", claim_id="claim-1", key_b64="a2V5")],
    )

    assert results == []


@pytest.mark.asyncio
async def test_case_insensitive_exact_phrase_match():
    embed_module.set_embed_client(_FakeEmbedClient())
    retrieve_module.set_retrieve_storage(_EmptyRetrieveStorage())
    sealed_storage_module.set_sealed_storage(
        _FakeSealedStorage(
            chunks_by_document={
                "doc-1": [{"ordinal": 0, "content": "The Secret Merger Closes In March"}]
            }
        )
    )

    results = await retrieve(
        user_jwt="t",
        user_id="user-1",
        query="secret merger",
        unlocked=[UnlockedDocument(document_id="doc-1", claim_id="claim-1", key_b64="a2V5")],
    )

    assert len(results) == 1
