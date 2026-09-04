"""Stage 7.13 — explicit generation config (CORRECTED post-launch).

The original pass here also set `safety_settings`, "confirmed live"
against docs that turned out to belong to a different product (Gemini
Enterprise Agent Platform, not the consumer Gemini API this codebase
calls). Caught live in production: every real chat turn failed with
`{"error":{"message":"The parameter 'safety_settings' is not available
on the Gemini API but it is available on the Gemini Enterprise Agent
Platform.","code":"invalid_request"}}`. `safety_settings` was removed
entirely as a result — see generate.py's own module docstring for the
full account.

What remains: `max_output_tokens` via `generation_config` (the
production error named only `safety_settings` as invalid, so this one
field's earlier live-check is retained, though at lower confidence
than it should be), and a direct regression guard that `safety_settings`
never quietly comes back, and that `GENERATION_CONFIG` never grows the
temperature/top_p/top_k fields this API was already confirmed not to
support.

Real fake-httpx-transport pattern (same as
test_stage_3_6_document_storage.py) so the request payload actually
sent is asserted directly, not just implied by behavior.
"""
import json as _json

import httpx
import pytest

from app.chat.generate import GEMINI_MAX_OUTPUT_TOKENS, GENERATION_CONFIG, GeminiGenerateClient, run_interaction


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
async def test_stream_text_sends_explicit_generation_config_and_no_safety_settings(
    monkeypatch,
):
    transport = _CapturingTransport(response_body=_sse_body("hi"))
    _patch_client(monkeypatch, transport)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    client = GeminiGenerateClient()
    deltas = [d async for d in client.stream_text(system_instruction="s", input_text="i")]

    assert deltas == ["hi"]
    assert len(transport.requests) == 1
    body = transport.requests[0]
    assert body["generation_config"] == {"max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS}
    assert "safety_settings" not in body


@pytest.mark.asyncio
async def test_run_interaction_sends_explicit_generation_config_and_no_safety_settings(
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
    assert "safety_settings" not in body


def test_generation_config_does_not_claim_unsupported_fields():
    # Regression guard: this exact field must never quietly come back —
    # a real production outage proved it's not valid on this API.
    assert "safety_settings" not in GENERATION_CONFIG
    # And the earlier, still-valid finding: temperature/top_p/top_k
    # don't exist in this API at all.
    assert "temperature" not in GENERATION_CONFIG
    assert "top_p" not in GENERATION_CONFIG
    assert "top_k" not in GENERATION_CONFIG
