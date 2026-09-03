"""Query-time image captioning for the rerank step.

Stage 1.3's extract.py leaves image chunk `content` permanently empty
(captioning was named as a capability in api-documentation.md but never
actually assigned to any stage's exit criteria — see that module's own
docstring). retrieve.py's reranker is a text-relevance model (Cohere
rerank-v4.0-pro); handed an empty string for every image candidate, it
can't meaningfully score them, so a real embedding correctly surfaced
in vector_search was almost always dropped before ever reaching the
caller — RELEVANCE_FLOOR sees an empty-string score and treats it as
"not relevant."

This module gives rerank (and the final RetrievedChunk it feeds) real
text to work with: the document's normalized `indexed` image (already
≤2048px WebP — same bytes /download signs a URL to) sent to Gemini as
a vision input, asked for a short factual description instead of an
extracted-task list (chat/action_items.py's job, not this one). Reused
across every chunk of the same document within one retrieve() call —
retrieve.py caches by document_id — since captioning the whole image
once is simpler and fast enough than per-tile captioning, and a wrong
caption only costs relevance ranking, never correctness (nothing here
is persisted; a bad or missing caption just makes that one candidate
rank low, the same "degrade, don't crash" posture the rest of this
package already uses for HyDE/rewrite failures).
"""
import base64
import logging

import httpx
from fastapi import HTTPException

from app.chat import generate as generate_module
from app.core.documents_storage import (
    DocumentsStorage,
    DocumentsStorageError,
    get_documents_storage,
)

logger = logging.getLogger(__name__)

IMAGE_CAPTION_SYSTEM_HEADER = (
    "Describe what is actually shown in the image below in 1-3 factual "
    "sentences — any visible text, objects, people, layout, charts, "
    "handwriting, whatever is really there. Do not guess at anything not "
    "visible. Respond with ONLY the description, no preamble, no markdown."
)


def _extract_text(interaction: dict) -> str:
    parts = []
    for step in interaction.get("steps", []):
        if step.get("type") == "model_output":
            for block in step.get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])
    return "".join(parts).strip()


async def caption_image(
    *,
    user_jwt: str,
    document_id: str,
    documents_storage: DocumentsStorage | None = None,
) -> str | None:
    """Returns a short description of the document's indexed image, or
    None on any failure (signed-url/download/generation) — callers treat
    None exactly like "no caption available," never as an error."""
    storage = documents_storage or get_documents_storage()
    try:
        signed_url = await storage.get_signed_url(
            user_jwt=user_jwt, document_id=document_id, variant="indexed"
        )
    except (DocumentsStorageError, HTTPException):
        return None

    try:
        async with httpx.AsyncClient() as client:
            image_resp = await client.get(signed_url)
        if image_resp.status_code >= 400:
            return None

        image_b64 = base64.b64encode(image_resp.content).decode()
        interaction = await generate_module.run_interaction(
            system_instruction=IMAGE_CAPTION_SYSTEM_HEADER,
            input_data=[
                {"type": "text", "text": "Describe this image now."},
                {"type": "image", "data": image_b64, "mime_type": "image/webp"},
            ],
        )
        text = _extract_text(interaction)
    except Exception:
        # Broad by design, same contract as retrieve/hyde.py and
        # retrieve/rewrite.py — a captioning failure degrades this one
        # candidate's rerank text, it never fails the whole retrieve()
        # call.
        logger.exception("Query-time image captioning failed for document %s", document_id)
        return None

    return text or None
