"""Stage 4.6 — action-item extraction into kanban. Exercises
extract_action_items against a fake DocumentsStorage + a fake httpx
transport for the chunks fetch + a monkeypatched run_interaction (no
real network), proving: a fixture document with known actionable
sentences proposes items traceable to real chunk ids; a document with
no chunks (including a sealed one, whose chunks were already deleted by
Stage 3.3) proposes zero items rather than erroring; a hallucinated
source_chunk_id is dropped; malformed/non-JSON model output degrades to
zero items rather than raising; a document that isn't the caller's own
returns None (404-not-403 at the route layer); and an image document
(whose chunks always have empty `content`, per extract.py) instead
sends the indexed image bytes to the model as an image content block
and pins every candidate to its first (only available) chunk id.
"""
import base64

import httpx
import pytest

from app.chat import generate as generate_module
from app.chat.action_items import extract_action_items
from app.chat.generate import GenerateError


class _FakeDocumentsStorage:
    def __init__(self, *, documents: dict[str, dict], signed_url: str | None = None):
        self.documents = documents
        self._signed_url = signed_url

    async def get_document(self, *, user_jwt, document_id):
        return self.documents.get(document_id)

    async def get_signed_url(self, *, user_jwt, document_id, variant):
        assert variant == "indexed"
        return self._signed_url


class _FakeChunksTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        *,
        chunks_by_document: dict[str, list[dict]],
        image_bytes_by_url: dict[str, bytes] | None = None,
    ):
        self._chunks_by_document = chunks_by_document
        self._image_bytes_by_url = image_bytes_by_url or {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if "/rest/v1/chunks" in str(request.url):
            params = dict(request.url.params)
            document_id = params["document_id"].removeprefix("eq.")
            return httpx.Response(200, json=self._chunks_by_document.get(document_id, []))
        image_bytes = self._image_bytes_by_url.get(str(request.url))
        if image_bytes is None:
            return httpx.Response(404)
        return httpx.Response(200, content=image_bytes)


def _patch_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


def _model_output_interaction(text: str) -> dict:
    return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}


@pytest.mark.asyncio
async def test_extracts_items_traceable_to_real_chunk_ids(monkeypatch):
    docs = _FakeDocumentsStorage(documents={"d1": {"id": "d1", "status": "ready"}})
    transport = _FakeChunksTransport(
        chunks_by_document={
            "d1": [
                {"id": "c1", "ordinal": 0, "content": "Please send the invoice by Friday."},
                {"id": "c2", "ordinal": 1, "content": "The sky was blue that day."},
            ]
        }
    )
    _patch_client(monkeypatch, transport)

    async def fake_run_interaction(*, system_instruction, input_data, tools=None, previous_interaction_id=None):
        assert "[[chunk:c1]]" in system_instruction
        return _model_output_interaction(
            '{"items": [{"title": "Send invoice", "description": "by Friday", "source_chunk_id": "c1"}]}'
        )

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    items = await extract_action_items(user_jwt="t", document_id="d1", documents_storage=docs)

    assert items == [
        {"title": "Send invoice", "description": "by Friday", "source_chunk_id": "c1"}
    ]


@pytest.mark.asyncio
async def test_document_with_no_chunks_returns_zero_items(monkeypatch):
    """Covers both a document that legitimately has no chunks yet and a
    sealed document, whose chunks Stage 3.3 already deleted — same code
    path, no special-casing needed."""
    docs = _FakeDocumentsStorage(documents={"d1": {"id": "d1", "status": "sealed"}})
    transport = _FakeChunksTransport(chunks_by_document={})
    _patch_client(monkeypatch, transport)

    called = False

    async def fake_run_interaction(**kwargs):
        nonlocal called
        called = True
        return _model_output_interaction("{}")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    items = await extract_action_items(user_jwt="t", document_id="d1", documents_storage=docs)

    assert items == []
    assert called is False  # never even calls generation for an empty document


@pytest.mark.asyncio
async def test_hallucinated_source_chunk_id_is_dropped(monkeypatch):
    docs = _FakeDocumentsStorage(documents={"d1": {"id": "d1", "status": "ready"}})
    transport = _FakeChunksTransport(
        chunks_by_document={"d1": [{"id": "c1", "ordinal": 0, "content": "Ship the report."}]}
    )
    _patch_client(monkeypatch, transport)

    async def fake_run_interaction(**kwargs):
        return _model_output_interaction(
            '{"items": [{"title": "Ship report", "description": "", "source_chunk_id": "does-not-exist"}]}'
        )

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    items = await extract_action_items(user_jwt="t", document_id="d1", documents_storage=docs)

    assert items == []


@pytest.mark.asyncio
async def test_malformed_model_output_degrades_to_zero_items(monkeypatch):
    docs = _FakeDocumentsStorage(documents={"d1": {"id": "d1", "status": "ready"}})
    transport = _FakeChunksTransport(
        chunks_by_document={"d1": [{"id": "c1", "ordinal": 0, "content": "Ship the report."}]}
    )
    _patch_client(monkeypatch, transport)

    async def fake_run_interaction(**kwargs):
        return _model_output_interaction("not json at all, sorry")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    items = await extract_action_items(user_jwt="t", document_id="d1", documents_storage=docs)

    assert items == []


@pytest.mark.asyncio
async def test_generate_error_degrades_to_zero_items(monkeypatch):
    docs = _FakeDocumentsStorage(documents={"d1": {"id": "d1", "status": "ready"}})
    transport = _FakeChunksTransport(
        chunks_by_document={"d1": [{"id": "c1", "ordinal": 0, "content": "Ship the report."}]}
    )
    _patch_client(monkeypatch, transport)

    async def fake_run_interaction(**kwargs):
        raise GenerateError("generate_call_failed", "upstream boom")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    items = await extract_action_items(user_jwt="t", document_id="d1", documents_storage=docs)

    assert items == []


@pytest.mark.asyncio
async def test_document_not_owned_returns_none(monkeypatch):
    docs = _FakeDocumentsStorage(documents={})

    items = await extract_action_items(
        user_jwt="t", document_id="does-not-exist", documents_storage=docs
    )

    assert items is None


@pytest.mark.asyncio
async def test_image_document_sends_indexed_bytes_as_image_block(monkeypatch):
    signed_url = "https://test-project.supabase.co/storage/v1/object/sign/indexed/fake.webp"
    fake_webp_bytes = b"\x00\x01\x02fake-webp-bytes"
    docs = _FakeDocumentsStorage(
        documents={"d1": {"id": "d1", "status": "ready", "mime": "image/jpeg"}},
        signed_url=signed_url,
    )
    transport = _FakeChunksTransport(
        chunks_by_document={
            "d1": [
                {"id": "c1", "ordinal": 0, "content": ""},
                {"id": "c2", "ordinal": 1, "content": ""},
            ]
        },
        image_bytes_by_url={signed_url: fake_webp_bytes},
    )
    _patch_client(monkeypatch, transport)

    async def fake_run_interaction(*, system_instruction, input_data, tools=None, previous_interaction_id=None):
        assert "c1" in system_instruction
        assert isinstance(input_data, list)
        image_block = next(b for b in input_data if b["type"] == "image")
        assert image_block["mime_type"] == "image/webp"
        assert base64.b64decode(image_block["data"]) == fake_webp_bytes
        return _model_output_interaction(
            '{"items": [{"title": "Water the plants", "description": "sticky note", "source_chunk_id": "c1"}]}'
        )

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    items = await extract_action_items(user_jwt="t", document_id="d1", documents_storage=docs)

    assert items == [
        {"title": "Water the plants", "description": "sticky note", "source_chunk_id": "c1"}
    ]


@pytest.mark.asyncio
async def test_image_document_with_unsigned_url_failure_returns_zero_items(monkeypatch):
    class _FailingSignedUrlStorage(_FakeDocumentsStorage):
        async def get_signed_url(self, *, user_jwt, document_id, variant):
            from app.core.documents_storage import DocumentsStorageError

            raise DocumentsStorageError("not_available", "no indexed file yet")

    docs = _FailingSignedUrlStorage(
        documents={"d1": {"id": "d1", "status": "ready", "mime": "image/png"}}
    )
    transport = _FakeChunksTransport(
        chunks_by_document={"d1": [{"id": "c1", "ordinal": 0, "content": ""}]}
    )
    _patch_client(monkeypatch, transport)

    called = False

    async def fake_run_interaction(**kwargs):
        nonlocal called
        called = True
        return _model_output_interaction("{}")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    items = await extract_action_items(user_jwt="t", document_id="d1", documents_storage=docs)

    assert items == []
    assert called is False
