"""Resolve explicit document context without searching unrelated documents."""

import re

from app.retrieve.image_caption import caption_image
from app.graph.cluster import get_graph_storage
from app.retrieve.retrieve import (
    FINAL_TOP_K,
    RELEVANCE_FLOOR,
    RetrievedChunk,
    get_rerank_client,
)

CLARIFICATION = "Which document, image, or topic would you like to discuss? Select a source or add a specific question so I can use the right evidence."


def needs_clarification(query: str, *, has_context: bool) -> bool:
    text = re.sub(r"[^\w\s]", "", query.lower()).strip()
    if text in {
        "hi",
        "hello",
        "hey",
        "help",
        "anything",
        "something",
        "tell me anything",
        "tell me something",
        "tell me something interesting",
    }:
        return True
    if has_context:
        return False
    generic_words = set(
        "please can could you tell me about explain summarize describe it this that these them the document documents file files image images picture pictures diagram chart table topic topics stuff more what whats is are do does think know talk chat show give a an overview and or everything anything something interesting random some all my of".split()
    )
    if text and set(text.split()) <= generic_words:
        return True
    return bool(
        re.fullmatch(
            r"(?:(?:please|can you|could you) )?(?:explain|summarize|describe|tell me about|what is|whats|what about|talk about|chat about)(?: (?:it|this|that|these|them|anything|something|the document|the file|the image|the picture|my documents|my files))?",
            text,
        )
    )


async def retrieve_document(
    *, user_jwt: str, document_id: str, query: str
) -> list[RetrievedChunk]:
    # This existing RLS-scoped endpoint reads only the chosen document. A missing
    # or sealed document has no candidates; never fall back to the vault search.
    rows = await get_graph_storage().get_node_chunks(
        user_jwt=user_jwt, document_id=document_id
    )
    if not rows:
        return []
    if all(not row.get("content") for row in rows):
        caption = await caption_image(user_jwt=user_jwt, document_id=document_id)
        for row in rows:
            row["content"] = caption or ""
    if query.strip().lower() == "summarize this document.":
        # Overview uses excerpts across reading order, rather than asking a
        # relevance model to score a question with no topical keywords.
        count = min(FINAL_TOP_K, len(rows))
        indices = [round(i * (len(rows) - 1) / max(count - 1, 1)) for i in range(count)]
        scored = [(i, 1.0) for i in indices]
    else:
        scored = await get_rerank_client().rerank(
            query=query,
            documents=[r["content"][:6000] for r in rows],
            top_n=FINAL_TOP_K,
        )
        scored = [(i, score) for i, score in scored if score >= RELEVANCE_FLOOR]
    return [
        RetrievedChunk(
            chunk_id=rows[i]["id"],
            document_id=document_id,
            ordinal=rows[i]["ordinal"],
            content=rows[i]["content"],
            meta=rows[i].get("meta") or {},
            relevance_score=score,
        )
        for i, score in scored
    ]
