"""Stage 1.3 — extract & chunk.

Host-agnostic (no FastAPI imports), operates on document_id + user_jwt
only — same design intent as normalize.py, see architecture-and-security.md
§1.

Text: no library needed. Originally straight character-window chunking;
Stage 7.1 kept the same window size/overlap but made the cut points
boundary-aware (paragraph > sentence > line > word, searched within a
fraction of the target size), so a chunk no longer opens or closes
mid-word — which degraded both embedding quality and the readability of
every chunk preview in the UI.

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

# Stage 7.1 — how far back from the ideal cut point `chunk_text` will
# look for a real boundary before giving up and hard-cutting. 20% of the
# target size: far enough back to reach the end of a normal sentence or
# paragraph, near enough that chunks stay close to the size everything
# downstream (embedding, rerank input, the UI's chunk previews) was
# tuned around. A fraction rather than a fixed char count so a caller
# passing a smaller `chunk_size` gets a proportional search window, not
# one that could swallow the whole chunk.
TEXT_CHUNK_BOUNDARY_SEARCH = 0.2

_PARAGRAPH_BREAK = "\n\n"
# Deliberately requires the trailing space/newline: a bare "." also ends
# "3.14", "Fig.", and "e.g.", none of which are sentence boundaries.
# This isn't a real sentence tokenizer and isn't trying to be — the
# fallbacks below (line break, then any whitespace) already guarantee a
# sane cut, so a missed sentence end costs chunk tidiness, never
# correctness. A proper tokenizer (nltk/spacy) would mean a heavy new
# dependency, which CLAUDE.md's memory governance rules out.
_SENTENCE_ENDINGS = (". ", "! ", "? ", ".\n", "!\n", "?\n")

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


def _find_boundary(text: str, *, window_start: int, ideal_end: int) -> int:
    """Best cut point in [window_start, ideal_end], preferring the
    strongest structural break available in that window.

    Returns a position to slice *up to* (exclusive), so the break itself
    stays with the chunk that ends on it rather than opening the next
    one. Falls back to `ideal_end` — the old hard character cut — when
    the window holds no boundary at all, which is the right answer for
    genuinely unbreakable input (a 1000-char base64 blob, minified
    source, a CJK run with no spaces).
    """
    window = text[window_start:ideal_end]

    paragraph_idx = window.rfind(_PARAGRAPH_BREAK)
    if paragraph_idx != -1:
        return window_start + paragraph_idx + len(_PARAGRAPH_BREAK)

    sentence_end = -1
    for ending in _SENTENCE_ENDINGS:
        idx = window.rfind(ending)
        if idx != -1:
            sentence_end = max(sentence_end, idx + len(ending))
    if sentence_end != -1:
        return window_start + sentence_end

    line_idx = window.rfind("\n")
    if line_idx != -1:
        return window_start + line_idx + 1

    for i in range(ideal_end - 1, window_start - 1, -1):
        if text[i].isspace():
            return i + 1

    return ideal_end


def _snap_to_word_start(text: str, pos: int, *, limit: int) -> int:
    """Move `pos` forward to the next word start, so a chunk never opens
    mid-word. Clamped to `limit` (the previous chunk's end) so snapping
    can only ever shrink the overlap, never skip past text entirely and
    leave a gap between two chunks.
    """
    if pos <= 0 or pos >= len(text) or text[pos - 1].isspace():
        return pos
    while pos < len(text) and not text[pos].isspace():
        pos += 1
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return min(pos, limit)


def chunk_text(
    text: str, *, chunk_size: int = TEXT_CHUNK_SIZE, overlap: int = TEXT_CHUNK_OVERLAP
) -> list[str]:
    """Stage 7.1 — chunks snap to real boundaries (paragraph > sentence >
    line > word) within `TEXT_CHUNK_BOUNDARY_SEARCH` of the target size,
    instead of the original raw character-offset slicing that could open
    or close a chunk mid-word. Same target size and overlap as before;
    only where the cut lands changed.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    search_span = max(1, int(chunk_size * TEXT_CHUNK_BOUNDARY_SEARCH))
    chunks: list[str] = []
    start = 0
    while start < len(text):
        ideal_end = start + chunk_size
        if ideal_end >= len(text):
            tail = text[start:].strip()
            if tail:
                chunks.append(tail)
            break

        window_start = max(start + 1, ideal_end - search_span)
        end = _find_boundary(text, window_start=window_start, ideal_end=ideal_end)

        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)

        next_start = _snap_to_word_start(text, end - overlap, limit=end)
        # Forward progress is a hard guarantee, not a hope: a caller
        # passing overlap >= chunk_size (or a boundary landing inside the
        # overlap region) would otherwise loop forever.
        start = next_start if next_start > start else end
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
