"""Stage 1.7 — generation client (Gemini, Interactions API).

Confirmed live against current docs before writing this, not from
memory: Gemini's REST API moved to a new `interactions` endpoint with a
step-based SSE event model (interaction.created -> step.start ->
step.delta -> step.stop -> interaction.completed), replacing the older
streamGenerateContent/candidates shape that training data would default
to assuming. Auth via `x-goog-api-key` header, not a query param or
Bearer token.

Model: gemini-3.5-flash-lite, not the docs' first-listed gemini-3.7-flash
— see GEMINI_MODEL's own comment for why (real-tested latency, not a
docs claim: 3.7-flash ran a mandatory "thought" step taking ~83s to
first visible text even at thinking_level "low", 3.5-flash-lite did the
same prompt in ~3s).

Only `step.delta` events with `delta.type == "text"` matter to this
client — text deltas are yielded as they arrive; every other event type
(interaction.created, step.start, step.stop, interaction.completed) is
ignored, since chat/stream.py only needs the raw token stream, not
Gemini's own step/usage bookkeeping.

Stage 7.12 — bounded retry. Zero retry logic existed anywhere here: a
single `httpx.ReadTimeout` or non-2xx response killed the whole turn
immediately (surfaced by chat/stream.py as one `error` SSE event, no
recovery attempt). Both `stream_text` and `run_interaction` now retry
once (`GENERATE_MAX_RETRIES`), after a real backoff
(`GENERATE_RETRY_BACKOFF_SECONDS`), on a `GenerateError` (non-2xx) or
`httpx.TransportError` (connection/timeout) — never on anything else,
so a real bug doesn't get silently retried and masked.

`stream_text`'s retry is deliberately narrower than `run_interaction`'s:
once any real text delta has already been yielded to the caller (and
therefore already forwarded to the client as a `token` SSE event —
chat/stream.py streams deltas through as they arrive, it doesn't
buffer), a retry would either duplicate that text or silently
overwrite it with a fresh generation the client already saw a
different draft of. Neither is acceptable, so a mid-stream failure
after any output has shipped is never retried — it propagates exactly
as before this stage, which is deliberately still Stage 7.14's problem
("clear partial-answer state on mid-stream error"), not this one's. A
failure before the first delta — the actual `httpx.ReadTimeout`/non-2xx
scenario this stage's exit criteria describes — is the case that's
actually safe to retry transparently, since the caller has seen
nothing yet.
"""
import asyncio
import json
import logging
import os
from typing import AsyncIterator, Protocol

import httpx

from app.core.http_client import CachedHttpClientMixin

logger = logging.getLogger(__name__)

GENERATE_MAX_RETRIES = 1  # bounded — one retry, never an infinite loop.
GENERATE_RETRY_BACKOFF_SECONDS = 1.0  # a real backoff, not an immediate
# re-hit of an API that may already be struggling.

GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
# gemini-3.7-flash was tried first (per CLAUDE.md's Gemini-for-generation
# choice) but real-tested at ~83s to first visible text for a trivial
# prompt — it runs a mandatory "thought" step regardless of
# thinking_level, unusable for real-time chat. gemini-3.5-flash-lite
# real-tested at ~3s for the same prompt and correctly followed the
# citation-marker instruction on a realistic RAG prompt — see Stage
# 1.7's conversation record for both real timed calls.
GEMINI_MODEL = "gemini-3.5-flash-lite"


class GenerateError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class GenerateClient(Protocol):
    model: str  # for the Langfuse "generation" span's model field

    def stream_text(self, *, system_instruction: str, input_text: str) -> AsyncIterator[str]:
        """Yields text deltas as they arrive, in order."""
        ...


def parse_sse_line(line: str) -> str | None:
    """Pure, network-free parse of one raw SSE line from the Gemini
    interactions stream. Returns a text delta if this line carries one,
    else None. Split out from stream_text so this exact parsing —
    including the `[DONE]` terminator, confirmed against a real
    streaming call rather than assumed from the docs, which don't
    mention it — is unit-testable without mocking httpx's streaming
    response."""
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None
    event = json.loads(payload)
    if event.get("event_type") != "step.delta":
        return None
    delta = event.get("delta", {})
    if delta.get("type") == "text" and delta.get("text"):
        return delta["text"]
    return None


class GeminiGenerateClient(CachedHttpClientMixin):
    model = GEMINI_MODEL
    # 30s wasn't enough — a live production request hit httpx.ReadTimeout
    # mid-generation (caught by a Phase 1 audit that actually made a real
    # chat call, not just local testing, where every prior call finished
    # in ~3s). 90s gives real headroom against network variance from
    # Render; stream.py now also surfaces a real `error` SSE event if
    # this still isn't enough, instead of the connection just dying
    # silently.
    _HTTP_CLIENT_KWARGS = {"timeout": 90.0}

    def __init__(self) -> None:
        self._api_key = os.environ.get("GEMINI_API_KEY", "")

    async def stream_text(
        self, *, system_instruction: str, input_text: str
    ) -> AsyncIterator[str]:
        client = self._client()
        attempt = 0
        while True:
            yielded_any = False
            try:
                async with client.stream(
                    "POST",
                    GEMINI_INTERACTIONS_URL,
                    headers={
                        "x-goog-api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GEMINI_MODEL,
                        "input": input_text,
                        "system_instruction": system_instruction,
                        "stream": True,
                    },
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise GenerateError("generate_call_failed", body.decode())

                    async for line in response.aiter_lines():
                        text = parse_sse_line(line)
                        if text:
                            yielded_any = True
                            yield text
                return
            except (GenerateError, httpx.TransportError):
                # Only ever retried before any real output has shipped
                # to the caller — see this module's docstring for why a
                # mid-stream failure after real text already streamed
                # must not be retried.
                if yielded_any or attempt >= GENERATE_MAX_RETRIES:
                    raise
                attempt += 1
                logger.warning(
                    "Gemini stream_text failed before any text was produced "
                    "(attempt %d/%d) — retrying after backoff",
                    attempt, GENERATE_MAX_RETRIES,
                )
                await asyncio.sleep(GENERATE_RETRY_BACKOFF_SECONDS)


async def run_interaction(
    *,
    system_instruction: str,
    input_data: str | list[dict],
    tools: list[dict] | None = None,
    previous_interaction_id: str | None = None,
) -> dict:
    """Stage 4.5 — a non-streaming interactions call, for tool-calling
    turns only (chat/stream.py's streaming stream_text is unaffected and
    unused here). Confirmed live against current docs before writing
    this (per CLAUDE.md's /api-check discipline): a non-streaming
    response's steps live under a top-level "steps" array; a
    function_call step carries "name"/"arguments"/"id" (not "call_id");
    a model_output step carries "content", a list of {"type": "text",
    "text": ...} blocks. Streaming's SSE shape for function_call steps
    is not documented anywhere findable at build time, which is exactly
    why this call is non-streaming — guessing at an undocumented
    streaming shape for a stretch feature isn't worth the risk of
    silently mis-parsing a tool call.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    payload: dict = {
        "model": GEMINI_MODEL,
        "input": input_data,
        "system_instruction": system_instruction,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    if previous_interaction_id:
        payload["previous_interaction_id"] = previous_interaction_id

    attempt = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    GEMINI_INTERACTIONS_URL,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
            if response.status_code >= 400:
                raise GenerateError("generate_call_failed", response.text)
            return response.json()
        except (GenerateError, httpx.TransportError):
            # Non-streaming — no partial output to worry about
            # duplicating, so this is always safe to retry within budget.
            if attempt >= GENERATE_MAX_RETRIES:
                raise
            attempt += 1
            logger.warning(
                "Gemini run_interaction failed (attempt %d/%d) — "
                "retrying after backoff",
                attempt, GENERATE_MAX_RETRIES,
            )
            await asyncio.sleep(GENERATE_RETRY_BACKOFF_SECONDS)


_client: GenerateClient = GeminiGenerateClient()


def get_generate_client() -> GenerateClient:
    return _client


def set_generate_client(client: GenerateClient) -> None:
    """Test seam — inject a fake generate client (deterministic, no network)."""
    global _client
    _client = client
