"""Regression for the recluster that returned 202 and then built nothing.

Live cause (2026-10-13): `run_clustering_job` fetched every ready document's
chunk embeddings in ONE request through a client with httpx's default 5-second
timeout; on the Render free tier that read timed out (`httpx.ReadTimeout`) and
the job died, leaving every document unplaced. The fetch is now paged and the
client's timeout fits a page.
"""
import httpx
import pytest

from app.graph.storage import DOCUMENTS_PER_EMBEDDING_PAGE, SupabaseGraphStorage


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, total_documents: int):
        self.docs = [
            {"id": f"doc-{i:03d}", "chunks": [{"embedding": "[0.1,0.2]"}]}
            for i in range(total_documents)
        ]
        self.requests: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/v1/documents"
        q = dict(request.url.params)
        self.requests.append(q)
        offset, limit = int(q["offset"]), int(q["limit"])
        return httpx.Response(200, json=self.docs[offset : offset + limit])


def _patch(monkeypatch, transport):
    real = httpx.AsyncClient
    seen: list[dict] = []

    def fake(*args, **kwargs):
        seen.append(dict(kwargs))
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    return seen


@pytest.mark.asyncio
async def test_embeddings_are_fetched_in_pages_and_joined_in_order(monkeypatch):
    transport = _Transport(total_documents=12)
    _patch(monkeypatch, transport)

    docs = await SupabaseGraphStorage().get_ready_documents_with_chunk_embeddings(
        user_jwt="t"
    )

    assert [d["id"] for d in docs] == [f"doc-{i:03d}" for i in range(12)]
    assert all(d["chunk_embeddings"] == [[0.1, 0.2]] for d in docs)
    # 12 documents at 5 a page: 3 requests, each with a stable order.
    assert [r["offset"] for r in transport.requests] == ["0", "5", "10"]
    assert all(r["limit"] == str(DOCUMENTS_PER_EMBEDDING_PAGE) for r in transport.requests)
    assert all(r["order"] == "id.asc" for r in transport.requests)


@pytest.mark.asyncio
async def test_an_exact_multiple_of_the_page_size_ends_cleanly(monkeypatch):
    transport = _Transport(total_documents=DOCUMENTS_PER_EMBEDDING_PAGE * 2)
    _patch(monkeypatch, transport)

    docs = await SupabaseGraphStorage().get_ready_documents_with_chunk_embeddings(
        user_jwt="t"
    )

    assert len(docs) == DOCUMENTS_PER_EMBEDDING_PAGE * 2
    # The last full page is followed by one empty page that says "no more".
    assert len(transport.requests) == 3


@pytest.mark.asyncio
async def test_no_documents_is_one_request_and_an_empty_list(monkeypatch):
    transport = _Transport(total_documents=0)
    _patch(monkeypatch, transport)

    docs = await SupabaseGraphStorage().get_ready_documents_with_chunk_embeddings(
        user_jwt="t"
    )

    assert docs == []
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_the_client_is_not_on_httpxs_five_second_default(monkeypatch):
    transport = _Transport(total_documents=1)
    seen = _patch(monkeypatch, transport)

    await SupabaseGraphStorage().get_ready_documents_with_chunk_embeddings(
        user_jwt="t"
    )

    timeout = seen[0]["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.read is not None and timeout.read >= 30
    assert timeout.connect is not None and timeout.connect <= 30


@pytest.mark.asyncio
async def test_a_failed_page_raises_instead_of_returning_a_partial_graph(monkeypatch):
    class _Failing(httpx.AsyncBaseTransport):
        calls = 0

        async def handle_async_request(self, request):
            _Failing.calls += 1
            if _Failing.calls == 1:
                rows = [{"id": f"d{i}", "chunks": []} for i in range(5)]
                return httpx.Response(200, json=rows)
            return httpx.Response(500, text="boom")

    _patch(monkeypatch, _Failing())

    from app.graph.storage import GraphStorageError

    with pytest.raises(GraphStorageError):
        await SupabaseGraphStorage().get_ready_documents_with_chunk_embeddings(
            user_jwt="t"
        )
