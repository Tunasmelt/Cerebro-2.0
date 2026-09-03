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

Off by default in `retrieve()` itself (`use_hyde=False`) — this stage's
own exit criteria called for a flag "so it can be A/B'd against direct
retrieval rather than replacing it outright," not a silent default-on
switch for every caller of `retrieve()`. Retrieval quality pass: live
chat turns (`chat/stream.py`'s `stream_chat`) now pass `use_hyde=True`
explicitly — a short, vague prompt is exactly where closing the
question/passage vocabulary gap earns its keep, and this was a fully-
built, tested capability sitting unused. Never a new way for retrieval
to fail either way: a failed or empty generation falls back to `None`,
and `retrieve()` falls back to embedding the real query exactly as it
does when `use_hyde` is False.

Stage 7.9 — made conditional. Turning HyDE on for *every* turn (the
retrieval-quality pass above) overrode this stage's own original "an
A/B-able flag, not a silent default" intent, and added a full extra
Gemini round-trip before the first token can appear on every single
question, whether or not the vocabulary-gap problem HyDE exists to
solve actually applies to it. No production Langfuse traffic was
available to this pass to measure the real cost against, so the
resolution taken is the exit criteria's other allowed path: make it
conditional. `should_use_hyde` — a short query is exactly the
"what's in the schedule"-shaped case this module's own docstring
above already uses as HyDE's motivating example: too few words to
share much vocabulary with dense indexed prose, which is precisely
where a hypothetical answer's passage-shaped language closes the gap.
A long, already-detailed query already contains specific vocabulary
likely to overlap real passages directly — HyDE's extra round-trip
buys it little, so skipping it there gets the latency back on exactly
the turns least likely to need it.
"""
import logging

from app.chat import generate as generate_module

logger = logging.getLogger(__name__)

HYDE_MAX_QUERY_WORDS = 8  # Stage 7.9 — a whitespace word count, not a
# token count: cheap, no tokenizer dependency, and good enough for a
# threshold that's a heuristic to begin with. Picked to separate short,
# vague prompts ("what's in the schedule", "explain the diagram") from
# queries that already carry enough specific vocabulary of their own
# ("how does the sealed-document unlock flow verify the passphrase-
# derived key server-side") to match real passages without HyDE's help.
# Not tuned against production data (none was available to this pass)
# — easy to retune later once Langfuse traffic makes the actual
# short/long split visible.

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


def should_use_hyde(query: str) -> bool:
    """Stage 7.9 — the caller-side decision of whether this turn's
    query is short/ambiguous enough for HyDE's extra Gemini round-trip
    to be worth paying for. Pure, no I/O — safe to call before
    retrieve() even starts."""
    return len(query.split()) <= HYDE_MAX_QUERY_WORDS


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
