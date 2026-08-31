"""Stage 1.2 — normalize pipeline.

Written host-agnostic (no FastAPI request/response objects imported,
operates purely on a document_id + user_jwt) so this can move to its own
Render service later without a rewrite — see architecture-and-security.md
§1.

PDFs: pikepdf structural optimization (lossless) — object streams
regenerated/compacted, Flate streams recompressed, linearized for
progressive rendering. Never touches page content/pixels, so it's
lossless by construction.

Images: Pillow .draft()-mode decode, JPEG/MPO only per Pillow's own docs
(no equivalent exists for PNG/WebP — they decode at full resolution
regardless, there's no DCT-scaled shortcut for non-block-based codecs) →
resize to a bounded max dimension → WebP re-encode. draft() is the
mechanism that actually protects RAM for large JPEGs, independent of the
final compressed size — see architecture-and-security.md §3.

Text: no normalize step is described anywhere in the docs for text/plain
(the pipeline section only covers PDFs and images) — passed through
unchanged into `indexed` so retrieval's "only ever reads indexed"
invariant still holds for every mime type, not just the two with a real
optimization step.
"""
import asyncio
import io
import os
from typing import Any, Protocol

import httpx
import pikepdf
from PIL import Image

MAX_IMAGE_DIMENSION = 2048  # px — not a number the docs specify; chosen
# as a reasonable bound (common vision-API ceiling) that still leaves
# output "meaningfully smaller" than typical >4000px source photos.
# Easy to retune later, not a load-bearing architectural decision.

WEBP_QUALITY = 87  # within the doc's stated "visually lossless, q85-90"


class NormalizeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def normalize_pdf(content: bytes) -> bytes:
    try:
        with pikepdf.open(io.BytesIO(content)) as pdf:
            out = io.BytesIO()
            pdf.save(
                out,
                compress_streams=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
                recompress_flate=True,
                linearize=True,
            )
            return out.getvalue()
    except pikepdf.PdfError as exc:
        raise NormalizeError("corrupt_pdf", str(exc)) from exc


def _decode_image(content: bytes, mime: str) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(content))
        if mime == "image/jpeg":
            # Pillow will pick the largest available DCT scale (1, 1/2,
            # 1/4, 1/8) that still covers the requested target — the
            # source is never decoded past that scale.
            img.draft("RGB", (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))
        img.load()
    except (Image.UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise NormalizeError("corrupt_image", str(exc)) from exc
    return img


def normalize_image(content: bytes, mime: str) -> tuple[bytes, str]:
    img = _decode_image(content, mime)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=WEBP_QUALITY)
    return out.getvalue(), "image/webp"


_EXT_BY_MIME = {"application/pdf": "pdf", "image/webp": "webp", "text/plain": "txt"}


class NormalizeStorage(Protocol):
    async def get_document(self, *, user_jwt: str, document_id: str) -> dict[str, Any]: ...
    async def download_original(self, *, user_jwt: str, path: str) -> bytes: ...
    async def upload_indexed(
        self, *, user_jwt: str, user_id: str, document_id: str, ext: str,
        content: bytes, mime: str,
    ) -> str: ...
    async def mark_normalized(self, *, user_jwt: str, document_id: str, storage_path: str) -> None: ...
    async def mark_failed(self, *, user_jwt: str, document_id: str, error_code: str) -> None: ...


class SupabaseNormalizeStorage:
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
            raise NormalizeError("document_not_found", document_id)
        return rows[0]

    async def download_original(self, *, user_jwt: str, path: str) -> bytes:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/storage/v1/object/originals/{path}",
                headers=self._headers(user_jwt),
            )
        if response.status_code >= 400:
            raise NormalizeError("original_download_failed", path)
        return response.content

    async def upload_indexed(
        self, *, user_jwt: str, user_id: str, document_id: str, ext: str,
        content: bytes, mime: str,
    ) -> str:
        path = f"{user_id}/{document_id}/indexed.{ext}"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._supabase_url}/storage/v1/object/indexed/{path}",
                headers={**self._headers(user_jwt), "Content-Type": mime},
                content=content,
            )
        if response.status_code >= 400:
            raise NormalizeError("indexed_upload_failed", path)
        return path

    async def mark_normalized(self, *, user_jwt: str, document_id: str, storage_path: str) -> None:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{self._supabase_url}/rest/v1/documents",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"id": f"eq.{document_id}"},
                json={"storage_path": storage_path},
            )
            await client.patch(
                f"{self._supabase_url}/rest/v1/ingest_jobs",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                params={"document_id": f"eq.{document_id}"},
                json={"state": "extracting"},
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


_storage: NormalizeStorage = SupabaseNormalizeStorage()


def get_normalize_storage() -> NormalizeStorage:
    return _storage


def set_normalize_storage(storage: NormalizeStorage) -> None:
    """Test seam — inject a fake storage/DB client."""
    global _storage
    _storage = storage


# Ingest concurrency = 1, non-negotiable per CLAUDE.md's memory governance
# guardrails — two normalize jobs must never run their heavy step at the
# same time on Render's single instance.
_normalize_lock = asyncio.Lock()


async def run_normalize_job(*, user_jwt: str, document_id: str) -> bool:
    """Returns True if the document was normalized and advanced to
    `extracting`, False if the job failed (and was marked so). Callers
    chaining the next pipeline stage should check this before proceeding."""
    storage = get_normalize_storage()
    document = await storage.get_document(user_jwt=user_jwt, document_id=document_id)
    mime = document["mime"]
    user_id = document["user_id"]

    async with _normalize_lock:
        content = await storage.download_original(
            user_jwt=user_jwt, path=document["original_storage_path"]
        )
        try:
            if mime == "application/pdf":
                normalized = normalize_pdf(content)
                out_mime = "application/pdf"
            elif mime == "text/plain":
                # No normalize pipeline step exists for plain text (the
                # architecture doc's normalize section only covers PDFs
                # and images) — pass the bytes through unchanged so
                # `indexed` still has a copy, keeping the "retrieval only
                # ever reads from indexed" invariant true for every mime.
                normalized, out_mime = content, "text/plain"
            else:
                normalized, out_mime = normalize_image(content, mime)
        except NormalizeError as exc:
            await storage.mark_failed(
                user_jwt=user_jwt, document_id=document_id, error_code=exc.code
            )
            return False

        ext = _EXT_BY_MIME[out_mime]
        indexed_path = await storage.upload_indexed(
            user_jwt=user_jwt,
            user_id=user_id,
            document_id=document_id,
            ext=ext,
            content=normalized,
            mime=out_mime,
        )
        await storage.mark_normalized(
            user_jwt=user_jwt, document_id=document_id, storage_path=indexed_path
        )
        return True
