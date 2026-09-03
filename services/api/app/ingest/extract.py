"""Stage 1.3 — extract & chunk.

Host-agnostic (no FastAPI imports), operates on document_id + user_jwt
only — same design intent as normalize.py, see architecture-and-security.md
§1.

Text: no library needed, straight character-window chunking.

PDF: pdfplumber for text extraction (chosen over pypdf/PyMuPDF — see the
Stage 1.3 conversation record; PyMuPDF's AGPL licensing was a specific
reason to avoid it). pikepdf (Stage 1.2) is structure-only and has no
practical text-extraction API. Reads the *indexed* (already
pikepdf-optimized) copy — optimization is lossless to content, so
extraction results are identical either way.

Image: tiles the *original* (from `originals`), not the Stage 1.2-resized
indexed copy — everything in `indexed` is already ≤2048px (Stage 1.2's
MAX_IMAGE_DIMENSION) and would never register as "oversized" here,
defeating the point. Tiling preserves detail a single downsized WebP
would lose. Chunk content is left empty for image tiles — captioning
isn't this stage's job (Stage 1.3's exit criteria only requires correct
document_id/ordinal/meta), and api-documentation.md attributes vision
captioning to Gemini, presumably a later embed-stage concern.
"""
import io
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import pdfplumber
from PIL import Image

from app.core.http_client import CachedHttpClientMixin
from app.ingest.concurrency import INGEST_LOCK

TEXT_CHUNK_SIZE = 1000  # chars — not specified anywhere in the docs;
# a plain, reasonable default for a first-pass chunker. Easy to retune,
# not a load-bearing architectural number.
TEXT_CHUNK_OVERLAP = 100

IMAGE_TILE_THRESHOLD = 2048  # px — matches Stage 1.2's own
# MAX_IMAGE_DIMENSION: anything the single normalized WebP would already
# have downscaled is exactly what tiling the original is meant to recover
# detail for.
IMAGE_TILE_SIZE = 1024


class ExtractError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class Chunk:
    ordinal: int
    content: str
    meta: dict[str, Any] = field(default_factory=dict)


def chunk_text(
    text: str, *, chunk_size: int = TEXT_CHUNK_SIZE, overlap: int = TEXT_CHUNK_OVERLAP
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    step = chunk_size - overlap
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start += step
    return chunks


def extract_text_chunks(text: str) -> list[Chunk]:
    return [
        Chunk(ordinal=i, content=piece, meta={})
        for i, piece in enumerate(chunk_text(text))
    ]


def extract_pdf_chunks(pdf_bytes: bytes) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = 0
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                for piece in chunk_text(page_text):
                    chunks.append(
                        Chunk(ordinal=ordinal, content=piece, meta={"page": page_number})
                    )
                    ordinal += 1
    except Exception as exc:  # pdfplumber/pdfminer don't document a single
        # stable exception type for malformed input — bound the catch to
        # this call rather than leaving a corrupt PDF to hang or crash
        # the ingest job.
        raise ExtractError("corrupt_pdf", str(exc)) from exc
    return chunks


def extract_image_chunks(original_bytes: bytes) -> list[Chunk]:
    try:
        img = Image.open(io.BytesIO(original_bytes))
        img.load()
    except (Image.UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ExtractError("corrupt_image", str(exc)) from exc

    width, height = img.size
    if max(width, height) <= IMAGE_TILE_THRESHOLD:
        return [Chunk(ordinal=0, content="", meta={"bbox": [0, 0, width, height]})]

    chunks: list[Chunk] = []
    ordinal = 0
    for y0 in range(0, height, IMAGE_TILE_SIZE):
        for x0 in range(0, width, IMAGE_TILE_SIZE):
            x1 = min(x0 + IMAGE_TILE_SIZE, width)
            y1 = min(y0 + IMAGE_TILE_SIZE, height)
            chunks.append(Chunk(ordinal=ordinal, content="", meta={"bbox": [x0, y0, x1, y1]}))
            ordinal += 1
    return chunks


class ExtractStorage(Protocol):
    async def get_document(self, *, user_jwt: str, document_id: str) -> dict[str, Any]: ...
    async def download_indexed(self, *, user_jwt: str, path: str) -> bytes: ...
    async def download_original(self, *, user_jwt: str, path: str) -> bytes: ...
    async def insert_chunks(
        self, *, user_jwt: str, document_id: str, user_id: str, chunks: list[Chunk]
    ) -> None: ...
    async def mark_extracted(self, *, user_jwt: str, document_id: str) -> None: ...
    async def mark_failed(self, *, user_jwt: str, document_id: str, error_code: str) -> None: ...


class SupabaseExtractStorage(CachedHttpClientMixin):
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {user_jwt}"}

    async def get_document(self, *, user_jwt: str, document_id: str) -> dict[str, Any]:
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/rest/v1/documents",
            headers=self._headers(user_jwt),
            params={"id": f"eq.{document_id}", "select": "*"},
        )
        rows = response.json()
        if not rows:
            raise ExtractError("document_not_found", document_id)
        return rows[0]

    async def _download(self, *, bucket: str, path: str, user_jwt: str) -> bytes:
        client = self._client()
        response = await client.get(
            f"{self._supabase_url}/storage/v1/object/{bucket}/{path}",
            headers=self._headers(user_jwt),
        )
        if response.status_code >= 400:
            raise ExtractError(f"{bucket}_download_failed", path)
        return response.content

    async def download_indexed(self, *, user_jwt: str, path: str) -> bytes:
        return await self._download(bucket="indexed", path=path, user_jwt=user_jwt)

    async def download_original(self, *, user_jwt: str, path: str) -> bytes:
        return await self._download(bucket="originals", path=path, user_jwt=user_jwt)

    async def insert_chunks(
        self, *, user_jwt: str, document_id: str, user_id: str, chunks: list[Chunk]
    ) -> None:
        if not chunks:
            return
        body = [
            {
                "document_id": document_id,
                "user_id": user_id,
                "ordinal": c.ordinal,
                "content": c.content,
                "meta": c.meta,
            }
            for c in chunks
        ]
        client = self._client()
        response = await client.post(
            f"{self._supabase_url}/rest/v1/chunks",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            json=body,
        )
        if response.status_code >= 400:
            raise ExtractError("chunk_insert_failed", document_id)

    async def mark_extracted(self, *, user_jwt: str, document_id: str) -> None:
        client = self._client()
        await client.patch(
            f"{self._supabase_url}/rest/v1/ingest_jobs",
            headers={**self._headers(user_jwt), "Content-Type": "application/json"},
            params={"document_id": f"eq.{document_id}"},
            json={"state": "embedding"},
        )

    async def mark_failed(self, *, user_jwt: str, document_id: str, error_code: str) -> None:
        client = self._client()
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


_storage: ExtractStorage = SupabaseExtractStorage()


def get_extract_storage() -> ExtractStorage:
    return _storage


def set_extract_storage(storage: ExtractStorage) -> None:
    """Test seam — inject a fake storage/DB client."""
    global _storage
    _storage = storage


async def run_extract_job(*, user_jwt: str, document_id: str) -> bool:
    """Returns True if chunks were created and the job advanced to
    `embedding`, False if it failed (and was marked so)."""
    storage = get_extract_storage()
    document = await storage.get_document(user_jwt=user_jwt, document_id=document_id)
    mime = document["mime"]
    user_id = document["user_id"]

    try:
        async with INGEST_LOCK:
            if document.get("source") == "capture":
                # Stage 5.5 — the whole point: no Storage object exists
                # for a captured thought, so there's nothing to
                # download. The text is chunked directly from the row
                # extract.py already has in hand.
                chunks = extract_text_chunks(document["captured_text"] or "")
            elif mime == "application/pdf":
                content = await storage.download_indexed(
                    user_jwt=user_jwt, path=document["storage_path"]
                )
                chunks = extract_pdf_chunks(content)
            elif mime in ("text/plain", "text/markdown"):
                content = await storage.download_indexed(
                    user_jwt=user_jwt, path=document["storage_path"]
                )
                chunks = extract_text_chunks(content.decode("utf-8", errors="replace"))
            else:
                original = await storage.download_original(
                    user_jwt=user_jwt, path=document["original_storage_path"]
                )
                chunks = extract_image_chunks(original)
    except ExtractError as exc:
        await storage.mark_failed(
            user_jwt=user_jwt, document_id=document_id, error_code=exc.code
        )
        return False

    await storage.insert_chunks(
        user_jwt=user_jwt, document_id=document_id, user_id=user_id, chunks=chunks
    )
    await storage.mark_extracted(user_jwt=user_jwt, document_id=document_id)
    return True
