"""Stage 1.4 — embed & job state machine (embedding step).

Host-agnostic, same design as normalize.py/extract.py. Uses Jina for
embeddings — adopted over Voyage/Cohere in Stage 1.4 for its broader
multimodal span and an explicit free tier (see CLAUDE.md §Stack).
Confirmed live against the real API before writing this, not from
memory: both jina-embeddings-v5-text-small (text) and
jina-embeddings-v5-omni-small (image) return 1024-dim vectors, matching
chunks.embedding halfvec(1024) exactly — no schema change needed. Also
confirmed PostgREST accepts a plain JSON array for the halfvec column
directly (not something to assume — pgvector types aren't native JSON).

Checkpointing: after each chunk is embedded, ingest_jobs.checkpoint is
updated with the last completed ordinal, so a crash mid-job resumes from
there instead of re-embedding already-done chunks.

Concurrency=1 via the pipeline-wide lock in app/ingest/concurrency.py.
"""
import base64
import io
import os
from typing import Any, Protocol

import httpx
from PIL import Image

from app.ingest.concurrency import INGEST_LOCK

TEXT_MODEL = "jina-embeddings-v5-text-small"
IMAGE_MODEL = "jina-embeddings-v5-omni-small"
EMBEDDING_DIMENSIONS = 1024  # must match chunks.embedding halfvec(1024)
JINA_EMBEDDINGS_URL = "https://api.jina.ai/v1/embeddings"


class EmbedError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def crop_tile(original_bytes: bytes, bbox: list[int]) -> bytes:
    img = Image.open(io.BytesIO(original_bytes))
    img.load()
    tile = img.crop(tuple(bbox))
    if tile.mode not in ("RGB", "RGBA"):
        tile = tile.convert("RGB")
    out = io.BytesIO()
    tile.save(out, format="PNG")
    return out.getvalue()


class EmbedClient(Protocol):
    async def embed_text(self, text: str) -> list[float]: ...
    async def embed_image(self, image_bytes: bytes) -> list[float]: ...


class JinaEmbedClient:
    def __init__(self) -> None:
        self._api_key = os.environ.get("JINA_API_KEY", "")

    async def _call(self, model: str, input_item: dict[str, str]) -> list[float]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                JINA_EMBEDDINGS_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "input": [input_item]},
            )
        if response.status_code >= 400:
            raise EmbedError("embed_call_failed", response.text)
        return response.json()["data"][0]["embedding"]

    async def embed_text(self, text: str) -> list[float]:
        return await self._call(TEXT_MODEL, {"text": text})

    async def embed_image(self, image_bytes: bytes) -> list[float]:
        b64 = base64.b64encode(image_bytes).decode()
        return await self._call(IMAGE_MODEL, {"image": f"data:image/png;base64,{b64}"})


_client: EmbedClient = JinaEmbedClient()


def get_embed_client() -> EmbedClient:
    return _client


def set_embed_client(client: EmbedClient) -> None:
    """Test seam — inject a fake embed client (deterministic, no network)."""
    global _client
    _client = client


class EmbedStorage(Protocol):
    async def get_document(self, *, user_jwt: str, document_id: str) -> dict[str, Any]: ...
    async def get_chunks(
        self, *, user_jwt: str, document_id: str
    ) -> list[dict[str, Any]]: ...
    async def download_original(self, *, user_jwt: str, path: str) -> bytes: ...
    async def get_checkpoint(self, *, user_jwt: str, document_id: str) -> dict[str, Any]: ...
    async def save_checkpoint(
        self, *, user_jwt: str, document_id: str, checkpoint: dict[str, Any]
    ) -> None: ...
    async def update_chunk_embedding(
        self, *, user_jwt: str, chunk_id: str, embedding: list[float]
    ) -> None: ...
    async def mark_ready(self, *, user_jwt: str, document_id: str) -> None: ...
    async def mark_failed(self, *, user_jwt: str, document_id: str, error_code: str) -> None: ...


class SupabaseEmbedStorage:
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {user_jwt}"}

    async def get_document(self, *, user_jwt: str, document_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/documents",
                headers=self._headers(user_jwt),
                params={"id": f"eq.{document_id}", "select": "*"},
            )
        rows = response.json()
        if not rows:
            raise EmbedError("document_not_found", document_id)
        return rows[0]

    async def get_chunks(self, *, user_jwt: str, document_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/chunks",
                headers=self._headers(user_jwt),
                params={
                    "document_id": f"eq.{document_id}",
                    "select": "id,ordinal,content,meta",
                    "order": "ordinal",
                },
            )
        return response.json()

    async def download_original(self, *, user_jwt: str, path: str) -> bytes:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/storage/v1/object/originals/{path}",
                headers=self._headers(user_jwt),
            )
        if response.status_code >= 400:
            raise EmbedError("original_download_failed", path)
        return response.content

    async def get_checkpoint(self, *, user_jwt: str, document_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/ingest_jobs",
                headers=self._headers(user_jwt),
                params={"document_id": f"eq.{document_id}", "select": "checkpoint"},
            )
        rows = response.json()
        if not rows or not rows[0].get("checkpoint"):
            return {}
        return rows[0]["checkpoint"]

    async def save_checkpoint(
        self, *, user_jwt: str, document_id: str, checkpoint: dict[str, Any]
    ) -> None:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{self._supabase_url}/rest/v1/ingest_jobs",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"document_id": f"eq.{document_id}"},
                json={"checkpoint": checkpoint},
            )

    async def update_chunk_embedding(
        self, *, user_jwt: str, chunk_id: str, embedding: list[float]
    ) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self._supabase_url}/rest/v1/chunks",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"id": f"eq.{chunk_id}"},
                json={"embedding": embedding},
            )
        if response.status_code >= 400:
            raise EmbedError("chunk_update_failed", chunk_id)

    async def mark_ready(self, *, user_jwt: str, document_id: str) -> None:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{self._supabase_url}/rest/v1/ingest_jobs",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"document_id": f"eq.{document_id}"},
                json={"state": "ready"},
            )
            await client.patch(
                f"{self._supabase_url}/rest/v1/documents",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"id": f"eq.{document_id}"},
                json={"status": "ready"},
            )

    async def mark_failed(self, *, user_jwt: str, document_id: str, error_code: str) -> None:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{self._supabase_url}/rest/v1/ingest_jobs",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"document_id": f"eq.{document_id}"},
                json={"state": "failed", "last_error": error_code},
            )
            await client.patch(
                f"{self._supabase_url}/rest/v1/documents",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"id": f"eq.{document_id}"},
                json={"status": "failed"},
            )


_storage: EmbedStorage = SupabaseEmbedStorage()


def get_embed_storage() -> EmbedStorage:
    return _storage


def set_embed_storage(storage: EmbedStorage) -> None:
    """Test seam — inject a fake storage/DB client."""
    global _storage
    _storage = storage


def _is_image_document(mime: str) -> bool:
    return mime not in ("application/pdf", "text/plain")


async def run_embed_job(*, user_jwt: str, document_id: str) -> bool:
    """Returns True if every chunk got an embedding and the job advanced
    to `ready`, False if it failed partway (and was marked so — whatever
    was checkpointed stays done, a retry resumes from there)."""
    storage = get_embed_storage()
    client = get_embed_client()

    document = await storage.get_document(user_jwt=user_jwt, document_id=document_id)
    is_image = _is_image_document(document["mime"])

    chunks = await storage.get_chunks(user_jwt=user_jwt, document_id=document_id)
    checkpoint = await storage.get_checkpoint(user_jwt=user_jwt, document_id=document_id)
    last_done_ordinal = checkpoint.get("last_embedded_ordinal", -1)

    original_bytes: bytes | None = None
    if is_image:
        original_bytes = await storage.download_original(
            user_jwt=user_jwt, path=document["original_storage_path"]
        )

    async with INGEST_LOCK:
        for chunk in chunks:
            if chunk["ordinal"] <= last_done_ordinal:
                continue  # already embedded before a prior crash
            try:
                if is_image:
                    tile = crop_tile(original_bytes, chunk["meta"]["bbox"])
                    embedding = await client.embed_image(tile)
                else:
                    embedding = await client.embed_text(chunk["content"])
            except EmbedError as exc:
                await storage.mark_failed(
                    user_jwt=user_jwt, document_id=document_id, error_code=exc.code
                )
                return False

            await storage.update_chunk_embedding(
                user_jwt=user_jwt, chunk_id=chunk["id"], embedding=embedding
            )
            await storage.save_checkpoint(
                user_jwt=user_jwt,
                document_id=document_id,
                checkpoint={"last_embedded_ordinal": chunk["ordinal"]},
            )

    await storage.mark_ready(user_jwt=user_jwt, document_id=document_id)
    return True
