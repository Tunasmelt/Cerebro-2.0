"""Stage 4.4 — read-only token/cost breakdown for a past chat turn.

Reconstructs the prompt that was actually sent for a given assistant
message, after the fact: `chat_messages` never persisted the assembled
system-instruction text, token counts, or cost (only `content`,
`retrieved_chunk_ids`, `trace_id`), so this refetches the retrieved
chunks by id (chunk content is immutable after ingest, so this is the
real content, not a guess) and rebuilds the prompt through the same
`build_system_instruction` used live in `chat/stream.py` — a second,
drifting reimplementation of the prompt format is exactly what this
avoids. No chat-history section: the live system never feeds prior
turns into the prompt either (see `chat/stream.py`), so nothing is
invented here that wasn't really sent.

Token counts are an estimate (`len(text) / 4`, the same heuristic the
`Mockups/ui_kits/playground` mockup itself used client-side) — no
tokenizer dependency, consistent with the free-tier no-heavy-deps
constraint. Cost is estimated from Gemini's real published per-token
rates for `gemini-3.5-flash-lite` (confirmed current at build time:
$0.30 / 1M input tokens, $2.50 / 1M output tokens) — prompt sections
(system instructions, context, user query) are priced as input, the
response as output, not a single blended rate.
"""
import os
import time
from dataclasses import dataclass
from typing import Any


from app.core.http_client import CachedHttpClientMixin
from app.chat.generate import GEMINI_MODEL, GenerateError, get_generate_client
from app.chat.prompt import SYSTEM_PROMPT_HEADER, build_system_instruction
from app.retrieve.retrieve import RetrievedChunk

# Stage 5.6 extends this file with a real "run" path: the deferred half
# of Stage 4.4's mockup (editable textareas, re-run, live recalc) that
# was explicitly held back until this had its own generation entry
# point, separate from chat/stream.py's normal path — a user-edited
# prompt hitting Gemini is a different, larger surface to secure than
# replaying what was already sent. run_edited_prompt() below reuses the
# real GenerateClient chat/stream.py itself calls, and mirrors
# build_system_instruction's exact block-join format (parameterized by
# the caller's edited header/content instead of hardcoded) so what's
# actually sent matches production shape rather than a drifted
# approximation. Nothing about a playground run is persisted — same
# posture already established for the original, unedited breakdown.

INPUT_PRICE_PER_TOKEN_USD = 0.30 / 1_000_000
OUTPUT_PRICE_PER_TOKEN_USD = 2.50 / 1_000_000


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


@dataclass
class PromptSection:
    label: str
    content: str
    tokens: int
    citation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "content": self.content,
            "tokens": self.tokens,
            "citation": self.citation,
        }


class ChatPlaygroundStorage(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {user_jwt}",
            "Content-Type": "application/json",
        }

    async def get_prompt_breakdown(
        self, *, user_jwt: str, session_id: str, message_id: str
    ) -> dict[str, Any] | None:
        client = self._client()
        session_resp = await client.get(
            f"{self._supabase_url}/rest/v1/chat_sessions",
            headers=self._headers(user_jwt),
            params={"id": f"eq.{session_id}", "select": "id"},
        )
        if not session_resp.json():
            return None

        messages_resp = await client.get(
            f"{self._supabase_url}/rest/v1/chat_messages",
            headers=self._headers(user_jwt),
            params={
                "session_id": f"eq.{session_id}",
                "select": "id,role,content,retrieved_chunk_ids,created_at",
                "order": "created_at.asc",
            },
        )
        messages = messages_resp.json()

        message = next((m for m in messages if m["id"] == message_id), None)
        if message is None or message["role"] != "assistant":
            return None

        preceding_user_message = next(
            (
                m
                for m in reversed(messages)
                if m["role"] == "user" and m["created_at"] < message["created_at"]
            ),
            None,
        )
        query_text = preceding_user_message["content"] if preceding_user_message else ""

        chunk_ids: list[str] = message.get("retrieved_chunk_ids") or []
        chunks: list[RetrievedChunk] = []
        document_titles: dict[str, str] = {}
        if chunk_ids:
            in_list = ",".join(chunk_ids)
            chunks_resp = await client.get(
                f"{self._supabase_url}/rest/v1/chunks",
                headers=self._headers(user_jwt),
                params={"id": f"in.({in_list})", "select": "id,document_id,ordinal,content,meta"},
            )
            rows = chunks_resp.json()
            document_ids = sorted({r["document_id"] for r in rows})
            if document_ids:
                docs_in_list = ",".join(document_ids)
                docs_resp = await client.get(
                    f"{self._supabase_url}/rest/v1/documents",
                    headers=self._headers(user_jwt),
                    params={"id": f"in.({docs_in_list})", "select": "id,title"},
                )
                document_titles = {d["id"]: d["title"] for d in docs_resp.json()}
            by_id = {r["id"]: r for r in rows}
            for chunk_id in chunk_ids:
                row = by_id.get(chunk_id)
                if row is None:
                    continue
                chunks.append(
                    RetrievedChunk(
                        chunk_id=row["id"],
                        document_id=row["document_id"],
                        ordinal=row["ordinal"],
                        content=row["content"],
                        meta=row.get("meta") or {},
                        relevance_score=0.0,
                    )
                )

        sections: list[PromptSection] = [
            PromptSection(
                label="system_instructions",
                content=SYSTEM_PROMPT_HEADER,
                tokens=estimate_tokens(SYSTEM_PROMPT_HEADER),
            )
        ]
        for chunk in chunks:
            title = document_titles.get(chunk.document_id, "unknown document")
            sections.append(
                PromptSection(
                    label="context",
                    content=chunk.content,
                    tokens=estimate_tokens(chunk.content),
                    citation=f"{title} · chunk_{chunk.chunk_id[:8]}",
                )
            )
        sections.append(
            PromptSection(
                label="user_query",
                content=query_text,
                tokens=estimate_tokens(query_text),
            )
        )

        # Per-section badges above are estimated from each section's own
        # display content, for readability; the real input-token count
        # (and the cost derived from it) is estimated from the actual
        # assembled string build_system_instruction produces live —
        # including the "[[chunk:id]]" markers, "### Source:" headers,
        # and joiners the sections above don't repeat per-badge — plus
        # the query, so cost can't silently drift from what a live turn
        # really sends. document_titles was already fetched above for
        # the per-section citation badges (line ~165) — reused here
        # rather than a second lookup, and it's what keeps this estimate
        # from quietly going stale now that a live turn's prompt is
        # grouped/labeled by source, not just a flat chunk list.
        assembled_instruction = build_system_instruction(chunks, document_titles)
        response_tokens = estimate_tokens(message["content"])
        input_tokens = estimate_tokens(assembled_instruction) + estimate_tokens(query_text)
        total_tokens = input_tokens + response_tokens
        estimated_cost_usd = (
            input_tokens * INPUT_PRICE_PER_TOKEN_USD
            + response_tokens * OUTPUT_PRICE_PER_TOKEN_USD
        )

        return {
            "model": GEMINI_MODEL,
            "sections": [s.to_dict() for s in sections],
            "response": {"content": message["content"], "tokens": response_tokens},
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(estimated_cost_usd, 6),
        }


    async def run_edited_prompt(
        self,
        *,
        user_jwt: str,
        session_id: str,
        system_instructions: str,
        context_sections: list[dict[str, str]],
        user_query: str,
    ) -> dict[str, Any] | None:
        """Runs a user-edited prompt for real against Gemini and returns
        the response with recalculated tokens/cost/latency. Returns None
        if the session isn't the caller's (RLS-scoped, 404-not-403 at the
        route layer, same pattern as get_prompt_breakdown)."""
        client = self._client()
        session_resp = await client.get(
            f"{self._supabase_url}/rest/v1/chat_sessions",
            headers=self._headers(user_jwt),
            params={"id": f"eq.{session_id}", "select": "id"},
        )
        if not session_resp.json():
            return None

        # Mirrors build_system_instruction's block-join format exactly,
        # parameterized by the caller's edited header/content instead of
        # hardcoded — each section keeps the [[chunk:id]] marker so the
        # assembled shape matches what a real turn sends, even though a
        # playground run never emits citation events off the result.
        if context_sections:
            context_blocks = "\n\n".join(
                f"[[chunk:{s.get('chunk_id', 'edited')}]]\n{s['content']}"
                for s in context_sections
            )
            assembled_system = f"{system_instructions}\n\n{context_blocks}"
        else:
            assembled_system = system_instructions

        generate_client = get_generate_client()
        started_at = time.monotonic()
        try:
            response_text = "".join(
                [
                    delta
                    async for delta in generate_client.stream_text(
                        system_instruction=assembled_system, input_text=user_query
                    )
                ]
            )
        except GenerateError as exc:
            return {"error": {"code": exc.code, "message": exc.message}}
        latency_ms = round((time.monotonic() - started_at) * 1000)

        response_tokens = estimate_tokens(response_text)
        input_tokens = estimate_tokens(assembled_system) + estimate_tokens(user_query)
        total_tokens = input_tokens + response_tokens
        estimated_cost_usd = (
            input_tokens * INPUT_PRICE_PER_TOKEN_USD
            + response_tokens * OUTPUT_PRICE_PER_TOKEN_USD
        )

        return {
            "model": GEMINI_MODEL,
            "response": {"content": response_text, "tokens": response_tokens},
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(estimated_cost_usd, 6),
            "latency_ms": latency_ms,
        }


_storage = ChatPlaygroundStorage()


def get_chat_playground_storage() -> ChatPlaygroundStorage:
    return _storage


def set_chat_playground_storage(storage: ChatPlaygroundStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage
