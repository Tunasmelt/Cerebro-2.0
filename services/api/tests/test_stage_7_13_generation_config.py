"""Stage 7.13 — explicit generation config.

Exit criteria: no temperature/max_output_tokens/top_p/top_k/safety-
settings were set anywhere in the Gemini call — everything relied on
platform defaults. Confirmed live against the current Interactions API
reference (see generate.py's own module docstring) that temperature,
top_p, and top_k don't exist in this API at all; what's actually
settable — max_output_tokens (generation_config) and safety_settings —
is now set explicitly on every call, both streaming (stream_text) and
non-streaming (run_interaction).

Real fake-httpx-transport pattern (same as
test_stage_3_6_document_storage.py) so the request payload actually
sent is asserted directly, not just implied by behavior.
"""
import json as _json

import httpx
import pytest

from app.chat.generate import (
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_SAFETY_SETTINGS,
    GeminiGenerateClient,
    run_interaction,
)


class _CapturingTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, response_body: bytes, content_type: str = "application/json"):
        self.response_body = response_body
        self.content_type = content_type
        self.requests: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(_json.loads(request.content))
        return httpx.Response(
            200, content=self.response_body, headers={"content-type": self.content_type}
        )


def _patch_client(monkeypatch, transport: httpx.AsyncBaseTransport) -> None:
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


def _sse_body(text: str) -> bytes:
    event = {"event_type": "step.delta", "delta": {"type": "text", "text": text}}
    return f"data: {_json.dumps(event)}\n\ndata: [DONE]\n\n".encode()


@pytest.mark.asyncio
async def test_stream_text_sends_explicit_generation_config_and_safety_settings(monkeypatch):
    transport = _CapturingTransport(response_body=_sse_body("hi"))
    _patch_client(monkeypatch, transport)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    client = GeminiGenerateClient()
    deltas = [d async for d in client.stream_text(system_instruction="s", input_text="i")]

    assert deltas == ["hi"]
    assert len(transport.requests) == 1
    body = transport.requests[0]
    assert body["generation_config"] == {"max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS}
    assert body["safety_settings"] == GEMINI_SAFETY_SETTINGS


@pytest.mark.asyncio
async def test_run_interaction_sends_explicit_generation_config_and_safety_settings(
    monkeypatch,
):
    transport = _CapturingTransport(response_body=_json.dumps({"steps": []}).encode())
    _patch_client(monkeypatch, transport)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    result = await run_interaction(system_instruction="s", input_data="q")

    assert result == {"steps": []}
    assert len(transport.requests) == 1
    body = transport.requests[0]
    assert body["generation_config"] == {"max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS}
    assert body["safety_settings"] == GEMINI_SAFETY_SETTINGS


def test_safety_settings_cover_the_four_standard_harm_categories_at_block_only_high():
    categories = {s["category"] for s in GEMINI_SAFETY_SETTINGS}
    assert categories == {
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
        "HARM_CATEGORY_HARASSMENT",
    }
    assert all(s["threshold"] == "BLOCK_ONLY_HIGH" for s in GEMINI_SAFETY_SETTINGS)


def test_generation_config_does_not_claim_unsupported_sampling_fields():
    # Stage 7.13's real finding: temperature/top_p/top_k don't exist in
    # the Interactions API at all — this must never silently regress
    # back to guessing at fields the live API doesn't accept.
    from app.chat.generate import GENERATION_CONFIG

    assert "temperature" not in GENERATION_CONFIG
    assert "top_p" not in GENERATION_CONFIG
    assert "top_k" not in GENERATION_CONFIG
