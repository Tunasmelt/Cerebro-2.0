"""Stage 5.2 — HyDE (Hypothetical Document Embeddings).

A real question and a real answer don't always sit close together in
embedding space — "How does quorum size affect Raft's availability?"
is question-shaped, but the chunks that actually answer it are
answer-shaped prose. HyDE's trick: ask a cheap generation call to write
a short, plausible hypothetical passage that *would* answer the query,
as if it were an excerpt from a real document, then embed *that*
instead of the literal query for vector search. Answer-shaped text
overlaps document chunks better than question-shaped text — the whole
technique rests on that asymmetry.

Reuses `chat/generate.py`'s `run_interaction`, the same non-streaming
entry point Stage 4.5/4.6/5.1 already call — no new generation path.

Embedded with `task="retrieval.passage"`, not `retrieval.query`: the
hypothetical text is deliberately document-shaped, meant to land near
real indexed passages in embedding space, so it should go through the
same passage-side adapter those passages were embedded with (Stage
1.4's asymmetric bi-encoder split) rather than the query-side one. This
is the one detail that makes HyDE's premise ("answer-shaped text
overlaps document chunks better") actually hold at the embedding level,
not just conceptually.

Strictly opt-in and never a new way for retrieval to fail: `retrieve()`
only takes this path when explicitly asked (`use_hyde=True`, off by
default and not wired into chat/stream.py — this stage's own exit
criteria calls for a flag "so it can be A/B'd against direct retrieval
rather than replacing it outright," not a silent default-on switch). A
failed or empty generation falls back to `None`, and `retrieve()` falls
back to embedding the real query exactly as it does when `use_hyde` is
False.
"""
import logging

from app.chat import generate as generate_module

logger = logging.getLogger(__name__)

HYDE_SYSTEM_HEADER = (
    "Write a short, plausible passage (2-4 sentences) that would answer "
    "the question below, as if it were an excerpt from a real document. "
    "Write it as a direct, confident answer in prose — not as a question, "
    "not as a list of things you don't know, not with any caveat about "
    "this being hypothetical. If you have no real basis for an answer, "
    "still write your best plausible guess at what a real answer would "
    "say. Respond with ONLY the passage, no quotes, no explanation, no "
    "markdown."
)


def _extract_text(interaction: dict) -> str:
    parts = []
    for step in interaction.get("steps", []):
        if step.get("type") == "model_output":
            for block in step.get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])
    return "".join(parts).strip()


async def generate_hypothetical_answer(*, query: str) -> str | None:
    """Returns the hypothetical passage, or None on any failure/empty
    output — retrieve() treats None exactly like "HyDE wasn't asked
    for," never as an error."""
    try:
        interaction = await generate_module.run_interaction(
            system_instruction=HYDE_SYSTEM_HEADER, input_data=query
        )
        text = _extract_text(interaction)
    except Exception:
        # Broad by design — same "never a new way for retrieval to
        # fail" contract as retrieve/rewrite.py's rewrite_query.
        logger.exception("HyDE hypothetical-answer generation failed")
        return None

    return text or None
