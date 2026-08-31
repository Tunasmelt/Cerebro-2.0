"""Stage 1.7 — chat SSE orchestration.

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
"""
import json
from typing import AsyncIterator

from app.chat.generate import get_generate_client
from app.chat.prompt import build_system_instruction, extract_citations
from app.chat.storage import get_chat_storage
from app.retrieve.retrieve import retrieve


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_chat(
    *, user_jwt: str, user_id: str, session_id: str, query: str
) -> AsyncIterator[str]:
    storage = get_chat_storage()
    generate_client = get_generate_client()

    await storage.save_message(
        user_jwt=user_jwt,
        session_id=session_id,
        user_id=user_id,
        role="user",
        content=query,
        retrieved_chunk_ids=[],
    )

    chunks = await retrieve(user_jwt=user_jwt, query=query)

    # Must be yielded before any token event — the frontend's graph pulse
    # animation depends on this ordering, and it's asserted by an
    # automated test (see test_stage_1_7_chat.py), not just documented.
    yield _sse(
        "retrieval",
        {
            "chunk_ids": [c.chunk_id for c in chunks],
            "document_ids": list({c.document_id for c in chunks}),
        },
    )

    system_instruction = build_system_instruction(chunks)
    full_text = ""
    async for delta in generate_client.stream_text(
        system_instruction=system_instruction, input_text=query
    ):
        full_text += delta
        yield _sse("token", {"text": delta})

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
    )

    yield _sse("done", {})
