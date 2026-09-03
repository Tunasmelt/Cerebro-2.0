"""Stage 4.6 — action-item extraction into kanban.

The one genuine cross-feature idea in Phase 4: RAG core (Phase 1) and
the kanban schema (Stage 4.1-4.2) had shared nothing but a `user_id`
until now. `cards.document_id` (Stage 4.1's "optional reference chip")
is exactly the connective tissue this stage needed and already existed.

Single-document extraction only — the target document's own chunks,
fetched directly by `document_id` (RLS-scoped via the caller's JWT, same
as every other query in this API), not a hybrid-retrieval query against
the whole vault. A sealed document naturally yields zero items with no
special-casing anywhere in this module: sealing (Stage 3.3) already
deletes a document's `chunks` rows entirely, so the chunk fetch below
just comes back empty, same "no relevant content returns nothing"
principle Stage 1.5's own exit criteria already established.

Candidates are never persisted here — this module only returns
suggestions. Confirming one is the caller doing a normal
`POST /boards/{id}/cards` (Stage 4.2, already accepts `document_id`) with
whichever candidate they picked; no new "confirm" endpoint exists
because none was needed. Uses the same non-streaming
`chat/generate.py` entry point Stage 4.5's tool-calling turn introduced
(no tools here, just a plain generation call asked to return JSON) —
still a separate call from `chat/stream.py`'s normal path.

The model is asked to reference one of the real chunk ids shown to it
(the same `[[chunk:id]]` marker convention `chat/prompt.py` already
uses) for every candidate's `source_chunk_id`; any item naming an id
that wasn't actually in the fetched chunk set — hallucinated, malformed,
or just missing — is dropped before ever reaching the caller, the same
distrust-by-default posture `chat/prompt.py`'s `extract_citations`
already applies to citations in a normal chat answer. Any failure to
get valid JSON back from the model (a parse error, a GenerateError) also
degrades to zero items rather than a hard error — consistent with the
same "no forced count" principle, not a new behavior.

Image documents (Stage 1.3's extract.py leaves image chunk `content`
permanently empty — captioning was deferred there and never built
anywhere since) previously always yielded zero candidates: the text
path above has nothing to read. Fixed by giving image documents their
own path that sends the normalized `indexed` bytes (already ≤2048px
WebP, comfortably under the Interactions API's 20MB inline-image cap —
confirmed live against current docs before writing this, per CLAUDE.md's
/api-check discipline: `input` accepts a flat list of
{"type":"text",...} / {"type":"image","data":<base64>,"mime_type":...}
blocks) straight to Gemini as an image content block, asking it to read
tasks directly off the image (whiteboards, screenshots, checklists,
handwritten notes) instead of off chunk text. There is no `[[chunk:id]]`
marker to reference for an image, so every candidate is pinned to the
document's first chunk id up front (one of `valid_chunk_ids` either
way) rather than trusting the model to echo one back.
"""
import base64
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException

from app.chat import generate as generate_module
from app.chat.generate import GenerateError
from app.core.documents_storage import (
    DocumentsStorage,
    DocumentsStorageError,
    get_documents_storage,
)

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}

ACTION_ITEM_SYSTEM_HEADER = (
    "You extract concrete, actionable tasks from the document text below. "
    'Only extract items that are real, specific action items explicitly '
    "supported by the text — never invent one. Respond with ONLY a JSON "
    'object of the exact shape {"items": [{"title": <str>, "description": '
    '<str>, "source_chunk_id": <str>}]}, using one of the chunk ids shown '
    "(the value inside [[chunk:...]]) for source_chunk_id on every item — "
    'never invent an id. If there are no real action items, respond with '
    '{"items": []}. No markdown, no prose outside the JSON object.'
)

IMAGE_ACTION_ITEM_SYSTEM_HEADER_TEMPLATE = (
    "You extract concrete, actionable tasks that are actually visible in the "
    "image below — text, handwriting, checklists, whiteboards, screenshots, "
    "sticky notes, calendars, and the like. Only extract items you can "
    "genuinely read in the image — never invent one. Respond with ONLY a "
    'JSON object of the exact shape {{"items": [{{"title": <str>, '
    '"description": <str>, "source_chunk_id": <str>}}]}}, using "{chunk_id}" '
    "as source_chunk_id for every item — it's the only id available for this "
    'image, do not invent another one. If there are no real action items '
    'visible, respond with {{"items": []}}. No markdown, no prose outside '
    "the JSON object."
)


@dataclass
class ActionItemCandidate:
    title: str
    description: str
    source_chunk_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "source_chunk_id": self.source_chunk_id,
        }


def _parse_candidates(raw_text: str, valid_chunk_ids: set[str]) -> list[ActionItemCandidate]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []

    candidates = []
    for item in parsed.get("items", []):
        if not isinstance(item, dict):
            continue
        source_chunk_id = item.get("source_chunk_id")
        title = item.get("title")
        if not title or source_chunk_id not in valid_chunk_ids:
            continue
        candidates.append(
            ActionItemCandidate(
                title=title,
                description=item.get("description", ""),
                source_chunk_id=source_chunk_id,
            )
        )
    return candidates


async def _fetch_document_chunks(
    *, user_jwt: str, document_id: str
) -> list[dict[str, Any]]:
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{supabase_url}/rest/v1/chunks",
            headers={"apikey": anon_key, "Authorization": f"Bearer {user_jwt}"},
            params={
                "document_id": f"eq.{document_id}",
                "select": "id,ordinal,content",
                "order": "ordinal.asc",
            },
        )
    if response.status_code >= 400:
        return []
    return response.json()


async def _extract_from_image(
    *,
    storage: DocumentsStorage,
    user_jwt: str,
    document_id: str,
    chunks: list[dict[str, Any]],
    valid_chunk_ids: set[str],
) -> list[dict[str, Any]]:
    # Every tile chunk (extract.py's extract_image_chunks) represents the
    # same underlying image — there's no [[chunk:id]] marker to have the
    # model choose one, so the first is the fixed anchor every candidate
    # gets pinned to.
    anchor_chunk_id = chunks[0]["id"]

    try:
        signed_url = await storage.get_signed_url(
            user_jwt=user_jwt, document_id=document_id, variant="indexed"
        )
    except (DocumentsStorageError, HTTPException):
        return []

    async with httpx.AsyncClient() as client:
        image_resp = await client.get(signed_url)
    if image_resp.status_code >= 400:
        return []

    # /download's own docstring: `indexed` is always a normalized WebP
    # for every image mime by the time normalize.py has run, regardless
    # of what the original was uploaded as.
    image_b64 = base64.b64encode(image_resp.content).decode()
    system_instruction = IMAGE_ACTION_ITEM_SYSTEM_HEADER_TEMPLATE.format(
        chunk_id=anchor_chunk_id
    )

    try:
        interaction = await generate_module.run_interaction(
            system_instruction=system_instruction,
            input_data=[
                {"type": "text", "text": "Extract the action items from this image now."},
                {"type": "image", "data": image_b64, "mime_type": "image/webp"},
            ],
        )
    except GenerateError:
        return []

    raw_text = "".join(
        block.get("text", "")
        for step in interaction.get("steps", [])
        if step.get("type") == "model_output"
        for block in step.get("content", [])
        if block.get("type") == "text"
    )
    return [c.to_dict() for c in _parse_candidates(raw_text, valid_chunk_ids)]


async def extract_action_items(
    *,
    user_jwt: str,
    document_id: str,
    documents_storage: DocumentsStorage | None = None,
) -> list[dict[str, Any]] | None:
    """Returns None if the document isn't the caller's own (404-not-403
    at the route layer, same pattern every other document route uses);
    otherwise a list of candidate dicts (possibly empty)."""
    storage = documents_storage or get_documents_storage()
    document = await storage.get_document(user_jwt=user_jwt, document_id=document_id)
    if document is None:
        return None

    chunks = await _fetch_document_chunks(user_jwt=user_jwt, document_id=document_id)
    if not chunks:
        return []

    valid_chunk_ids = {c["id"] for c in chunks}

    if document.get("mime") in IMAGE_MIME_TYPES:
        return await _extract_from_image(
            storage=storage,
            user_jwt=user_jwt,
            document_id=document_id,
            chunks=chunks,
            valid_chunk_ids=valid_chunk_ids,
        )

    context_blocks = "\n\n".join(f"[[chunk:{c['id']}]]\n{c['content']}" for c in chunks)
    system_instruction = f"{ACTION_ITEM_SYSTEM_HEADER}\n\n{context_blocks}"

    try:
        interaction = await generate_module.run_interaction(
            system_instruction=system_instruction,
            input_data="Extract the action items now.",
        )
    except GenerateError:
        return []

    raw_text = "".join(
        block.get("text", "")
        for step in interaction.get("steps", [])
        if step.get("type") == "model_output"
        for block in step.get("content", [])
        if block.get("type") == "text"
    )
    return [c.to_dict() for c in _parse_candidates(raw_text, valid_chunk_ids)]
