"""Stage 1.7 — chat SSE orchestration. Stage 1.8 adds Langfuse tracing:
the whole turn is one root `chat_turn` span/trace; five of the six
expected spans (embed_query, vector_search, fts_search, rrf_fuse,
rerank) nest under it automatically from inside retrieve() — this
module only owns the sixth, `generate`, plus the root span itself.

Exit criteria: emits `retrieval` (real chunk/document IDs) before any
`token` event, then tokens, then `citation` events, then `done`. This
ordering is structural here, not incidental — retrieve() is fully
awaited and its event yielded before the generate_client is ever
touched, so there is no interleaving to get wrong.

Citations are only computed after the full response text is assembled
(extract_citations needs the complete text to find every marker, and
must run before `done` per the exit criteria's ordering) and are
validated against the real retrieved chunk set — see prompt.py's
extract_citations docstring.

The turn's real trace_id (None when tracing is unconfigured — see
core/tracing.py) is stored on the assistant's chat_messages row, so a
past conversation can link back to its own Langfuse trace later.

Error handling (added after a live Phase 1 audit caught this the hard
way): a real production request hit httpx.ReadTimeout mid-generation —
Gemini took longer than the client's timeout from Render's network on
that occasion. The exception propagated unhandled straight through this
generator and Starlette's StreamingResponse, which just closes the
connection — the client saw `retrieval` and then nothing: no error
event, no `done`, no way to tell "the server failed" from "still
working." The whole body is now wrapped in try/except so any failure —
retrieval, generation, storage — surfaces as a real `error` SSE event
before the connection closes, instead of dying silently.
"""
import json
from typing import AsyncIterator

from app.chat.generate import get_generate_client
from app.chat.prompt import build_system_instruction, extract_citations
from app.chat.storage import get_chat_storage
from app.core.tracing import get_tracer
from app.retrieve.retrieve import retrieve


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_chat(
    *, user_jwt: str, user_id: str, session_id: str, query: str
) -> AsyncIterator[str]:
    storage = get_chat_storage()
    generate_client = get_generate_client()
    tracer = get_tracer()

    try:
        with tracer.start_as_current_observation(
            as_type="span", name="chat_turn", input={"query": query}
        ) as root_span:
            trace_id = tracer.get_current_trace_id()

            await storage.save_message(
                user_jwt=user_jwt,
                session_id=session_id,
                user_id=user_id,
                role="user",
                content=query,
                retrieved_chunk_ids=[],
            )

            chunks = await retrieve(user_jwt=user_jwt, query=query)

            # Must be yielded before any token event — the frontend's
            # graph pulse animation depends on this ordering, and it's
            # asserted by an automated test (see test_stage_1_7_chat.py),
            # not just documented.
            yield _sse(
                "retrieval",
                {
                    "chunk_ids": [c.chunk_id for c in chunks],
                    "document_ids": list({c.document_id for c in chunks}),
                },
            )

            system_instruction = build_system_instruction(chunks)
            full_text = ""
            with tracer.start_as_current_observation(
                as_type="generation",
                name="generate",
                model=getattr(generate_client, "model", None),
                input={"system_instruction": system_instruction, "query": query},
            ) as gen_span:
                async for delta in generate_client.stream_text(
                    system_instruction=system_instruction, input_text=query
                ):
                    full_text += delta
                    yield _sse("token", {"text": delta})
                gen_span.update(output=full_text)

            citations = extract_citations(full_text, chunks)
            for citation in citations:
                yield _sse(
                    "citation",
                    {"chunk_id": citation.chunk_id, "document_id": citation.document_id},
                )

            await storage.save_message(
                user_jwt=user_jwt,
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=full_text,
                retrieved_chunk_ids=[c.chunk_id for c in chunks],
                trace_id=trace_id,
            )

            root_span.update(
                output={"answer": full_text, "citation_count": len(citations)}
            )
    except Exception as exc:
        yield _sse("error", {"code": "chat_turn_failed", "message": str(exc)})
        return

    yield _sse("done", {})
