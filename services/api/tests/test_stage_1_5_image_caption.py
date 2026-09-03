"""retrieve/image_caption.py — the query-time captioning fix for
retrieve.py's rerank step (image chunks always have empty `content`;
see retrieve.py's own module docstring for the bug this closes).
Exercises caption_image directly: a signed-url + image download +
monkeypatched run_interaction happy path, and every failure mode
(signed-url error, download error, generation error, empty output)
degrading to None rather than raising — retrieve.py depends on that
contract to never let a captioning failure fail the whole retrieve()
call.
"""
import base64

import httpx
import pytest
from fastapi import HTTPException

from app.chat import generate as generate_module
from app.chat.generate import GenerateError
from app.core.documents_storage import DocumentsStorageError
from app.retrieve.image_caption import caption_image


class _FakeDocumentsStorage:
    def __init__(self, *, signed_url: str | None = None, raises: Exception | None = None):
        self._signed_url = signed_url
        self._raises = raises

    async def get_signed_url(self, *, user_jwt, document_id, variant):
        assert variant == "indexed"
        if self._raises:
            raise self._raises
        return self._signed_url


def _model_output_interaction(text: str) -> dict:
    return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}


@pytest.mark.asyncio
async def test_captions_the_indexed_image(monkeypatch):
    signed_url = "https://test-project.supabase.co/storage/v1/object/sign/indexed/fake.webp"
    fake_webp_bytes = b"fake-webp-bytes"
    docs = _FakeDocumentsStorage(signed_url=signed_url)

    class _FakeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            assert str(request.url) == signed_url
            return httpx.Response(200, content=fake_webp_bytes)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **kw: real_client(*a, transport=_FakeTransport(), **kw)
    )

    async def fake_run_interaction(*, system_instruction, input_data):
        assert isinstance(input_data, list)
        image_block = next(b for b in input_data if b["type"] == "image")
        assert image_block["mime_type"] == "image/webp"
        assert base64.b64decode(image_block["data"]) == fake_webp_bytes
        return _model_output_interaction("A hand-drawn org chart on a whiteboard.")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    result = await caption_image(user_jwt="t", document_id="d1", documents_storage=docs)

    assert result == "A hand-drawn org chart on a whiteboard."


@pytest.mark.asyncio
async def test_signed_url_failure_returns_none():
    docs = _FakeDocumentsStorage(raises=DocumentsStorageError("not_available", "no indexed file yet"))

    result = await caption_image(user_jwt="t", document_id="d1", documents_storage=docs)

    assert result is None


@pytest.mark.asyncio
async def test_signed_url_http_exception_returns_none():
    docs = _FakeDocumentsStorage(raises=HTTPException(status_code=502, detail="boom"))

    result = await caption_image(user_jwt="t", document_id="d1", documents_storage=docs)

    assert result is None


@pytest.mark.asyncio
async def test_download_failure_returns_none(monkeypatch):
    signed_url = "https://test-project.supabase.co/storage/v1/object/sign/indexed/fake.webp"
    docs = _FakeDocumentsStorage(signed_url=signed_url)

    class _FailingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(404)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **kw: real_client(*a, transport=_FailingTransport(), **kw)
    )

    result = await caption_image(user_jwt="t", document_id="d1", documents_storage=docs)

    assert result is None


@pytest.mark.asyncio
async def test_generate_error_returns_none(monkeypatch):
    signed_url = "https://test-project.supabase.co/storage/v1/object/sign/indexed/fake.webp"
    docs = _FakeDocumentsStorage(signed_url=signed_url)

    class _FakeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, content=b"bytes")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **kw: real_client(*a, transport=_FakeTransport(), **kw)
    )

    async def fake_run_interaction(**kwargs):
        raise GenerateError("generate_call_failed", "upstream boom")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    result = await caption_image(user_jwt="t", document_id="d1", documents_storage=docs)

    assert result is None


@pytest.mark.asyncio
async def test_empty_model_output_returns_none(monkeypatch):
    signed_url = "https://test-project.supabase.co/storage/v1/object/sign/indexed/fake.webp"
    docs = _FakeDocumentsStorage(signed_url=signed_url)

    class _FakeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, content=b"bytes")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **kw: real_client(*a, transport=_FakeTransport(), **kw)
    )

    async def fake_run_interaction(**kwargs):
        return _model_output_interaction("")

    monkeypatch.setattr(generate_module, "run_interaction", fake_run_interaction)

    result = await caption_image(user_jwt="t", document_id="d1", documents_storage=docs)

    assert result is None
