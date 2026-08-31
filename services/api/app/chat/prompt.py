"""Stage 1.7 — prompt assembly and citation extraction.

The model is instructed to cite retrieved chunks inline using a
distinctive marker carrying the chunk's real id — [[chunk:<uuid>]] —
rather than free-form numbering, so extraction never has to guess which
citation maps to which chunk. Extracted markers are then validated
against the actual retrieved chunk set before becoming `citation`
events: a marker naming a chunk id that wasn't really retrieved (a
model hallucination, or a malformed id) is dropped, never trusted. This
is the exit criteria's actual point — "no citation pointing at a chunk
ID that wasn't actually retrieved."
"""
import re
from dataclasses import dataclass

from app.retrieve.retrieve import RetrievedChunk

_CITATION_RE = re.compile(r"\[\[chunk:([0-9a-fA-F-]{36})\]\]")

SYSTEM_PROMPT_HEADER = (
    "You are answering questions using only the context chunks provided "
    "below. Cite the chunk(s) you used for each claim by inserting "
    "[[chunk:<id>]] immediately after the relevant sentence, using the "
    "exact id shown for that chunk — never invent an id. If the context "
    "doesn't contain the answer, say so plainly instead of guessing."
)


@dataclass
class Citation:
    chunk_id: str
    document_id: str


def build_system_instruction(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return (
            SYSTEM_PROMPT_HEADER
            + "\n\nNo relevant context was found for this question."
        )
    context_blocks = "\n\n".join(
        f"[[chunk:{c.chunk_id}]]\n{c.content}" for c in chunks
    )
    return f"{SYSTEM_PROMPT_HEADER}\n\n{context_blocks}"


def extract_citations(text: str, retrieved_chunks: list[RetrievedChunk]) -> list[Citation]:
    """Only returns citations for chunk ids that were actually in
    retrieved_chunks — a marker for any other id (hallucinated or
    malformed) is silently dropped, not forwarded to the client."""
    by_id = {c.chunk_id: c.document_id for c in retrieved_chunks}
    seen: set[str] = set()
    citations: list[Citation] = []
    for match in _CITATION_RE.finditer(text):
        chunk_id = match.group(1)
        if chunk_id not in by_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        citations.append(Citation(chunk_id=chunk_id, document_id=by_id[chunk_id]))
    return citations
