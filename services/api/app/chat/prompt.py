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

Retrieval quality pass: `_CITATION_RE` originally only matched a bare
36-char UUID, which is what every real chunk id looks like *except* a
sealed-document match — `retrieve.py`'s `_sealed_exact_matches` mints
ids shaped `<document_id>:<ordinal>`, so a citation for sealed content
could never actually match and was always silently dropped. Widened to
accept anything up to the closing `]]`; `extract_citations`'s existing
`chunk_id not in by_id` check is still what actually gates trust, not
the regex shape, so this doesn't loosen what gets accepted as real.

Also: `build_system_instruction` originally handed the model anonymous
chunk blobs with no document name attached anywhere — a real, reported
gap once documents beyond a lone image/PDF were in play. A user asking
"what does the schedule say vs the PDF" got an answer from a model that
had no way to know which chunk belonged to which file. `document_titles`
(optional, so every existing caller that doesn't have titles handy still
gets the old flat format) groups chunks under a "### Source: <title>"
header per document, in first-appearance order (chunks already arrive
rerank-sorted, so the most relevant source still leads), and the header
text below now explicitly tells the model sources are labeled and to
compare across them when a question spans more than one.
"""
import re
from dataclasses import dataclass

from app.retrieve.retrieve import RetrievedChunk

_CITATION_RE = re.compile(r"\[\[chunk:([^\]]+)\]\]")

SYSTEM_PROMPT_HEADER = (
    "You are answering questions using only the context chunks provided "
    "below. Where present, each group of chunks is labeled with its "
    "source document under a \"### Source: <name>\" header — when a "
    "question spans more than one source, compare or synthesize across "
    "all of the relevant ones rather than answering from just one, and "
    "name the source when it helps disambiguate (e.g. \"the PDF says...\" "
    "or \"the schedule image shows...\"). Cite the chunk(s) you used for "
    "each claim by inserting [[chunk:<id>]] immediately after the "
    "relevant sentence, using the exact id shown for that chunk — never "
    "invent an id. If the context doesn't contain the answer, say so "
    "plainly instead of guessing.\n\n"
    "The chunks themselves are raw source text and may contain markdown "
    "syntax — tables built from | pipes, **bold**/*italic* markers, `code` "
    "backticks, bullet dashes, heading #s. That formatting is an artifact "
    "of the source file, not part of the answer: read through it for the "
    "actual content and write your answer as plain, natural prose. Never "
    "copy a raw table row, a literal *, #, or | character, or any other "
    "markdown syntax out of a chunk into your response — describe what it "
    "says instead."
)


@dataclass
class Citation:
    chunk_id: str
    document_id: str


def build_system_instruction(
    chunks: list[RetrievedChunk], document_titles: dict[str, str] | None = None
) -> str:
    if not chunks:
        return (
            SYSTEM_PROMPT_HEADER
            + "\n\nNo relevant context was found for this question."
        )

    def _chunk_block(c: RetrievedChunk) -> str:
        return f"[[chunk:{c.chunk_id}]]\n{c.content}"

    if not document_titles:
        # No titles available (e.g. the playground's older call sites) —
        # unchanged flat format, one block per chunk in rerank order.
        context_blocks = "\n\n".join(_chunk_block(c) for c in chunks)
        return f"{SYSTEM_PROMPT_HEADER}\n\n{context_blocks}"

    groups: dict[str, list[RetrievedChunk]] = {}
    document_order: list[str] = []
    for c in chunks:
        if c.document_id not in groups:
            groups[c.document_id] = []
            document_order.append(c.document_id)
        groups[c.document_id].append(c)

    sections = [
        f'### Source: "{document_titles.get(document_id, "Untitled document")}"\n'
        + "\n\n".join(_chunk_block(c) for c in groups[document_id])
        for document_id in document_order
    ]
    return f"{SYSTEM_PROMPT_HEADER}\n\n" + "\n\n".join(sections)


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
