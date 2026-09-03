"""Stage 5.1 — query rewriting.

`retrieve()` gets no chat history today (`chat/stream.py`'s own
docstring already notes the live system never feeds prior turns into
the generation prompt) — a genuinely ambiguous follow-up like "what
about the other one?" embeds and searches exactly that literal text,
with no pronoun resolved. This module is the fix: a cheap, non-
streaming generation call (`chat/generate.py`'s `run_interaction`, the
same one Stage 4.5's tool-calling turn and Stage 4.6's action-item
extraction already use — no new generation entry point needed)
reformulates the raw query into a standalone one using a handful of
recent messages, before anything is embedded.

Strictly an optional quality improvement, never a new way for
retrieval to fail: any exception from the rewrite call — a
`GenerateError`, a malformed response, anything — falls back to the
original, un-rewritten query. `retrieve()` calling this is the only
thing that changes; a rewrite failure looks identical to a user who
just typed a fully standalone query.
"""
import logging

from app.chat import generate as generate_module

logger = logging.getLogger(__name__)

# How many trailing messages of context to show the rewrite call — a
# handful of turns is enough to resolve a pronoun or "the other one"
# without ballooning the cost of what's meant to be a cheap call. Not
# specified anywhere in the docs — a reasonable, easy-to-retune default,
# same category as retrieve.py's own RELEVANCE_FLOOR.
HISTORY_MESSAGE_LIMIT = 6

REWRITE_SYSTEM_HEADER = (
    "You rewrite a user's follow-up question into a standalone question, "
    "using the recent conversation below to resolve pronouns and vague "
    "references (\"it\", \"the other one\", \"that\") and to make an "
    "otherwise ambiguous or multi-part question self-contained. Preserve "
    "the user's actual intent exactly — never answer the question, never "
    "add information that wasn't asked for. If the question is already "
    "standalone, return it unchanged. Respond with ONLY the rewritten "
    "question, no quotes, no explanation, no markdown."
)


def _extract_text(interaction: dict) -> str:
    parts = []
    for step in interaction.get("steps", []):
        if step.get("type") == "model_output":
            for block in step.get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])
    return "".join(parts).strip()


async def rewrite_query(*, query: str, recent_messages: list[dict[str, str]]) -> str:
    """recent_messages: [{"role": "user"|"assistant", "content": str}, ...],
    chronological order (oldest first) — same shape chat_storage's
    get_recent_messages returns. Returns the rewritten query, or the
    original `query` unchanged on any failure or empty output."""
    if not recent_messages:
        return query

    history_text = "\n".join(
        f"{m['role']}: {m['content']}" for m in recent_messages[-HISTORY_MESSAGE_LIMIT:]
    )
    system_instruction = f"{REWRITE_SYSTEM_HEADER}\n\nRecent conversation:\n{history_text}"

    try:
        interaction = await generate_module.run_interaction(
            system_instruction=system_instruction, input_data=query
        )
        rewritten = _extract_text(interaction)
    except Exception:
        # Broad by design — this function's entire contract is "never a
        # new way for retrieval to fail," so a rewrite-side bug must
        # degrade exactly like a network timeout would, not propagate.
        logger.exception("query rewrite failed, falling back to raw query")
        return query

    return rewritten or query
