"""Stage 7.12 — bounded retry on Gemini timeout/failure.

Exit criteria: zero retry logic existed anywhere in generation — a
single httpx.ReadTimeout or non-2xx response killed the whole turn
immediately. Added one bounded, backed-off retry to both stream_text
(streaming, chat/stream.py's live path) and run_interaction
(non-streaming, HyDE/rewrite/captioning/tool calls).

stream_text tests use a hand-built fake httpx client (bypassing real
network entirely, injected via CachedHttpClientMixin's lazily-created
`_http_client` attribute — see http_client.py) so a mid-stream failure
can be simulated deterministically: real httpx transports don't give
fine-grained control over "raise partway through iterating a response
body" the way this needs. run_interaction tests use the established
real-httpx-transport pattern (test_stage_3_6_document_storage.py) since
it's non-streaming and that's simpler there.
"""
import json

import httpx
import pytest

from app.chat import generate as generate_module
from app.chat.generate import GENERATE_MAX_RETRIES, GeminiGenerateClient, run_interaction


def _delta_line(text: str) -> str:
    return f"data: {json.dumps({'event_type': 'step.delta', 'delta': {'type': 'text', 'text': text}})}"


class _FakeStreamResponse:
    def __init__(self, *, status_code: int, lines: list[str], error_after: int | None = None):
        self.status_code = status_code
        self._lines = lines
        self._error_after = error_after

    async def aread(self) -> bytes:
        return b"upstream error body"

    async def aiter_lines(self):
        for i, line in enumerate(self._lines):
            if self._error_after is not None and i == self._error_after:
                raise httpx.ReadTimeout("simulated mid-stream timeout")
            yield line


class _FakeStreamCM:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc_info):
        return False


class _RaisingStreamCM:
    """Simulates the connection itself failing before any response
    headers even arrive — client.stream(...) raising on __aenter__."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def __aenter__(self):
        raise self._exc

    async def __aexit__(self, *exc_info):
        return False


class _FakeHttpxClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def stream(self, method, url, **kwargs):
        response = self._responses[self.call_count]
        self.call_count += 1
        if isinstance(response, Exception):
            return _RaisingStreamCM(response)
        return _FakeStreamCM(response)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    # Real retries would otherwise wait GENERATE_RETRY_BACKOFF_SECONDS
    # (1.0s) for real — no reason to actually slow the suite down for it.
    monkeypatch.setattr(generate_module, "GENERATE_RETRY_BACKOFF_SECONDS", 0.0)


def _client_with_fake_transport(responses) -> tuple[GeminiGenerateClient, _FakeHttpxClient]:
    client = GeminiGenerateClient()
    fake = _FakeHttpxClient(responses)
    client._http_client = fake  # bypasses real httpx entirely
    return client, fake


# --- stream_text: recovers from a transient failure before any text ----------


@pytest.mark.asyncio
async def test_stream_text_recovers_from_a_connection_error_before_any_text():
    good = _FakeStreamResponse(status_code=200, lines=[_delta_line("Hello"), _delta_line(" world")])
    client, fake = _client_with_fake_transport([httpx.ConnectError("simulated"), good])

    deltas = [d async for d in client.stream_text(system_instruction="s", input_text="i")]

    assert deltas == ["Hello", " world"]
    assert fake.call_count == 2


@pytest.mark.asyncio
async def test_stream_text_recovers_from_a_non_2xx_response_before_any_text():
    failing = _FakeStreamResponse(status_code=503, lines=[])
    good = _FakeStreamResponse(status_code=200, lines=[_delta_line("recovered")])
    client, fake = _client_with_fake_transport([failing, good])

    deltas = [d async for d in client.stream_text(system_instruction="s", input_text="i")]

    assert deltas == ["recovered"]
    assert fake.call_count == 2


# --- stream_text: bounded, not infinite ---------------------------------------


@pytest.mark.asyncio
async def test_stream_text_gives_up_after_the_retry_budget_is_exhausted():
    always_failing = [httpx.ConnectError("simulated")] * (GENERATE_MAX_RETRIES + 5)
    client, fake = _client_with_fake_transport(always_failing)

    with pytest.raises(httpx.ConnectError):
        async for _ in client.stream_text(system_instruction="s", input_text="i"):
            pass

    # Exactly the original attempt plus the bounded retry budget — not
    # an infinite loop, not more than the budget allows.
    assert fake.call_count == GENERATE_MAX_RETRIES + 1


# --- stream_text: never retries once real text has already streamed ---------


@pytest.mark.asyncio
async def test_stream_text_does_not_retry_a_mid_stream_failure_after_text_shipped():
    response = _FakeStreamResponse(
        status_code=200, lines=[_delta_line("Hello"), _delta_line(" world")], error_after=1
    )
    client, fake = _client_with_fake_transport([response])

    delivered = []
    with pytest.raises(httpx.ReadTimeout):
        async for d in client.stream_text(system_instruction="s", input_text="i"):
            delivered.append(d)

    assert delivered == ["Hello"]
    assert fake.call_count == 1  # no retry attempted — real output already shipped


# --- run_interaction: same bounded-retry contract, no streaming to protect ---


class _FlakyRunInteractionTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, fail_times: int, mode: str = "timeout"):
        self.fail_times = fail_times
        self.mode = mode
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            if self.mode == "timeout":
                raise httpx.ReadTimeout("simulated", request=request)
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"steps": []})


def _patch_httpx_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


@pytest.mark.asyncio
async def test_run_interaction_recovers_from_a_transient_timeout(monkeypatch):
    transport = _FlakyRunInteractionTransport(fail_times=1, mode="timeout")
    _patch_httpx_client(monkeypatch, transport)

    result = await run_interaction(system_instruction="s", input_data="q")

    assert result == {"steps": []}
    assert transport.call_count == 2


@pytest.mark.asyncio
async def test_run_interaction_recovers_from_a_non_2xx_response(monkeypatch):
    transport = _FlakyRunInteractionTransport(fail_times=1, mode="http_error")
    _patch_httpx_client(monkeypatch, transport)

    result = await run_interaction(system_instruction="s", input_data="q")

    assert result == {"steps": []}
    assert transport.call_count == 2


@pytest.mark.asyncio
async def test_run_interaction_gives_up_after_persistent_failure(monkeypatch):
    transport = _FlakyRunInteractionTransport(fail_times=99, mode="timeout")
    _patch_httpx_client(monkeypatch, transport)

    with pytest.raises(httpx.ReadTimeout):
        await run_interaction(system_instruction="s", input_data="q")

    assert transport.call_count == GENERATE_MAX_RETRIES + 1
