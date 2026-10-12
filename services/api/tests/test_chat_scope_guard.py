from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app.chat import query_scope, stream as stream_module
from app.core.evidence_storage import EvidenceError, SupabaseEvidenceStorage
from app.routes import chat as chat_routes


@pytest.mark.parametrize(
    "query",
    [
        "explain",
        "tell me anything",
        "summarize this",
        "what is the image",
        "hello",
        "can you explain this?",
        "tell me about some stuff",
        "what do you think",
        "the image",
    ],
)
def test_vague_first_turn_requires_clarification(query):
    assert query_scope.needs_clarification(query, has_context=False)


def test_named_question_and_contextual_followup_are_not_blocked():
    assert not query_scope.needs_clarification(
        "How does authentication work?", has_context=False
    )
    assert not query_scope.needs_clarification("summarize this", has_context=True)


@pytest.mark.asyncio
async def test_clarification_has_no_retrieval_generation_or_citations(monkeypatch):
    saved = []

    async def save_message(**kwargs):
        saved.append(kwargs)

    async def recent(**kwargs):
        return []

    monkeypatch.setattr(
        stream_module,
        "get_chat_storage",
        lambda: SimpleNamespace(get_recent_messages=recent, save_message=save_message),
    )
    monkeypatch.setattr(
        stream_module,
        "retrieve",
        lambda **_: pytest.fail("vague query searched the vault"),
    )
    monkeypatch.setattr(stream_module, "get_generate_client", lambda: SimpleNamespace())
    events = [
        part
        async for part in stream_module.stream_chat(
            user_jwt="owner", user_id="u", session_id="s", query="explain this"
        )
    ]
    assert [part.splitlines()[0] for part in events] == [
        "event: retrieval",
        "event: token",
        "event: done",
    ]
    assert query_scope.CLARIFICATION in saved[-1]["content"]
    assert all(not row["retrieved_chunk_ids"] for row in saved)


@pytest.mark.asyncio
async def test_explicit_document_summary_reads_only_selected_document(monkeypatch):
    calls = []

    async def chunks(**kwargs):
        calls.append(kwargs)
        return [
            {"id": f"c{i}", "ordinal": i, "content": f"Selected source {i}", "meta": {}}
            for i in range(20)
        ]

    monkeypatch.setattr(
        query_scope,
        "get_graph_storage",
        lambda: SimpleNamespace(get_node_chunks=chunks),
    )
    result = await query_scope.retrieve_document(
        user_jwt="owner", document_id="selected", query="Summarize this document."
    )
    assert calls == [{"user_jwt": "owner", "document_id": "selected"}]
    assert {row.document_id for row in result} == {"selected"}
    assert result[0].ordinal == 0 and result[-1].ordinal == 19


@pytest.mark.asyncio
async def test_scoped_followup_drops_irrelevant_chunks_without_vault_fallback(
    monkeypatch,
):
    async def chunks(**_):
        return [{"id": "c", "ordinal": 0, "content": "unrelated", "meta": {}}]

    async def rerank(**_):
        return [(0, 0.0)]

    monkeypatch.setattr(
        query_scope,
        "get_graph_storage",
        lambda: SimpleNamespace(get_node_chunks=chunks),
    )
    monkeypatch.setattr(
        query_scope, "get_rerank_client", lambda: SimpleNamespace(rerank=rerank)
    )
    assert (
        await query_scope.retrieve_document(
            user_jwt="owner", document_id="selected", query="missing topic"
        )
        == []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("document,status", [(None, 404), ({"status": "sealed"}, 423)])
async def test_scope_route_rejects_foreign_missing_and_sealed(
    monkeypatch, document, status
):
    async def session(**_):
        return {"id": "s"}

    async def get_document(**_):
        return document

    monkeypatch.setattr(
        chat_routes, "get_chat_storage", lambda: SimpleNamespace(get_session=session)
    )
    from app.core import documents_storage

    monkeypatch.setattr(
        documents_storage,
        "get_documents_storage",
        lambda: SimpleNamespace(get_document=get_document),
    )
    request = SimpleNamespace(
        state=SimpleNamespace(user_jwt="owner", user={"sub": "u"})
    )
    response = await chat_routes.stream(
        request, "s", chat_routes.StreamBody(query="summary", document_id=UUID(int=1))
    )
    assert response.status_code == status


@pytest.mark.asyncio
async def test_evidence_schema_fallback_keeps_real_legacy_excerpt_and_owner_auth():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(400, json={"code": "PGRST200"})
        return httpx.Response(
            200,
            json=[
                {
                    "id": "c",
                    "document_id": "d",
                    "content": "Exact cited words",
                    "meta": {},
                    "documents": {
                        "id": "d",
                        "title": "Notes",
                        "status": "ready",
                        "mime": "text/plain",
                    },
                }
            ],
        )

    storage = SupabaseEvidenceStorage()
    storage._url = "https://db.test"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage._http_client = client
        result = await storage.get_evidence(user_jwt="owner", chunk_id="c")
    assert result["legacy"] and result["content"] == "Exact cited words"
    assert all(request.headers["authorization"] == "Bearer owner" for request in calls)
    assert all(request.url.params["id"] == "eq.c" for request in calls)


@pytest.mark.asyncio
async def test_evidence_storage_failure_is_not_interpreted_as_a_chunk():
    storage = SupabaseEvidenceStorage()
    storage._url = "https://db.test"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(500, json={"message": "private"})
        )
    ) as client:
        storage._http_client = client
        with pytest.raises(EvidenceError, match="Could not load source evidence"):
            await storage.get_evidence(user_jwt="owner", chunk_id="c")


@pytest.mark.asyncio
async def test_previous_clarification_does_not_become_document_context(monkeypatch):
    saved = []

    async def save_message(**kwargs):
        saved.append(kwargs)

    async def recent(**kwargs):
        return [{"role": "assistant", "content": query_scope.CLARIFICATION}]

    monkeypatch.setattr(
        stream_module,
        "get_chat_storage",
        lambda: SimpleNamespace(get_recent_messages=recent, save_message=save_message),
    )
    monkeypatch.setattr(
        stream_module,
        "retrieve",
        lambda **_: pytest.fail("retrieved after clarification"),
    )
    monkeypatch.setattr(stream_module, "get_generate_client", lambda: SimpleNamespace())
    events = [
        part
        async for part in stream_module.stream_chat(
            user_jwt="owner", user_id="u", session_id="s", query="explain this"
        )
    ]
    assert "Which document" in events[1]


@pytest.mark.asyncio
async def test_scoped_stream_tells_model_the_application_selected_the_source(
    monkeypatch,
):
    generated = []

    async def recent(**_):
        return []

    async def save(**_):
        pass

    async def retrieve(**_):
        from app.retrieve.retrieve import RetrievedChunk

        return [
            RetrievedChunk(
                chunk_id="c",
                document_id="d",
                ordinal=0,
                content="A source fact",
                meta={},
                relevance_score=1,
            )
        ]

    async def titles(**_):
        return {"d": "Selected notes"}

    async def reinforce(**_):
        pass

    async def stream_text(**kwargs):
        generated.append(kwargs)
        yield "A source fact [[chunk:c]]"

    monkeypatch.setattr(
        stream_module,
        "get_chat_storage",
        lambda: SimpleNamespace(get_recent_messages=recent, save_message=save),
    )
    monkeypatch.setattr(stream_module, "retrieve_document", retrieve)
    monkeypatch.setattr(
        stream_module,
        "get_documents_storage",
        lambda: SimpleNamespace(get_titles=titles),
    )
    monkeypatch.setattr(
        stream_module,
        "get_chunk_edges_storage",
        lambda: SimpleNamespace(reinforce_co_retrieval=reinforce),
    )
    monkeypatch.setattr(
        stream_module,
        "get_generate_client",
        lambda: SimpleNamespace(stream_text=stream_text),
    )
    events = [
        part
        async for part in stream_module.stream_chat(
            user_jwt="owner",
            user_id="u",
            session_id="s",
            query="Summarize this document.",
            document_id="d",
        )
    ]
    assert '"scope_document_id": "d"' in events[0]
    assert "explicitly selected this source" in generated[0]["system_instruction"]
    assert any(part.startswith("event: citation") for part in events)
