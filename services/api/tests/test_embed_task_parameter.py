"""Regression test for the missing-`task`-parameter bug: Jina v5's
retrieval is an asymmetric bi-encoder (a query embedded without
task="retrieval.query" against passages embedded without
task="retrieval.passage" both fall back to whatever Jina's default
adapter is, degrading retrieval — confirmed live in production, where a
real, correctly-embedded image chunk ranked 16th of 27 total chunks for
a directly-relevant query before this fix). Exercises the real
JinaEmbedClient/CohereEmbedClient/VoyageEmbedClient HTTP call shape
against a fake transport, proving the right task/input_type reaches the
request body for both the ingest (passage) and query paths — not just
that a fake in-memory EmbedClient accepts the new parameter.

Voyage's own asymmetric `input_type` (query vs document) was initially
missed in this same fix — the first draft's comment claimed Voyage's
multimodal API had no query/document distinction at all, which turned
out to be wrong when actually checked against Voyage's current docs
(it has one, same shape as Jina/Cohere). Caught by the user asking
"what about cohere and voyage with the same issue?" rather than by any
test, which is exactly why this file also locks down Voyage's mapping
now instead of trusting the comment.
"""
import json

import httpx
import pytest

from app.ingest.embed import CohereEmbedClient, JinaEmbedClient, VoyageEmbedClient


class _FakeJinaTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.requests: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1024}]})


class _FakeCohereTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.requests: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        return httpx.Response(200, json={"embeddings": {"float": [[0.1] * 1024]}})


def _patch_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


@pytest.mark.asyncio
async def test_jina_embed_text_defaults_to_retrieval_passage(monkeypatch):
    transport = _FakeJinaTransport()
    _patch_client(monkeypatch, transport)

    await JinaEmbedClient().embed_text("some chunk content")

    assert transport.requests[0]["task"] == "retrieval.passage"


@pytest.mark.asyncio
async def test_jina_embed_text_query_uses_retrieval_query(monkeypatch):
    transport = _FakeJinaTransport()
    _patch_client(monkeypatch, transport)

    await JinaEmbedClient().embed_text("what's in the image?", task="retrieval.query")

    assert transport.requests[0]["task"] == "retrieval.query"


@pytest.mark.asyncio
async def test_jina_embed_image_defaults_to_retrieval_passage(monkeypatch):
    transport = _FakeJinaTransport()
    _patch_client(monkeypatch, transport)

    await JinaEmbedClient().embed_image(b"fake-image-bytes")

    assert transport.requests[0]["task"] == "retrieval.passage"


@pytest.mark.asyncio
async def test_cohere_embed_text_maps_task_to_input_type(monkeypatch):
    transport = _FakeCohereTransport()
    _patch_client(monkeypatch, transport)
    client = CohereEmbedClient()

    await client.embed_text("chunk content")
    await client.embed_text("a query", task="retrieval.query")

    assert transport.requests[0]["input_type"] == "search_document"
    assert transport.requests[1]["input_type"] == "search_query"


class _FakeVoyageTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.requests: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1024}]})


@pytest.mark.asyncio
async def test_voyage_embed_text_maps_task_to_input_type(monkeypatch):
    transport = _FakeVoyageTransport()
    _patch_client(monkeypatch, transport)
    client = VoyageEmbedClient()

    await client.embed_text("chunk content")
    await client.embed_text("a query", task="retrieval.query")

    assert transport.requests[0]["input_type"] == "document"
    assert transport.requests[1]["input_type"] == "query"


@pytest.mark.asyncio
async def test_voyage_embed_image_defaults_to_document(monkeypatch):
    transport = _FakeVoyageTransport()
    _patch_client(monkeypatch, transport)

    await VoyageEmbedClient().embed_image(b"fake-image-bytes")

    assert transport.requests[0]["input_type"] == "document"
