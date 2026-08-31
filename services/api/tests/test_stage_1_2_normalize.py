"""Stage 1.2 — normalize pipeline.

Exit criteria: PDFs pass through pikepdf structural optimization; images
pass through draft-mode decode and WebP re-encode; both land in
`indexed`, originals untouched in `originals`.

Pure-function tests (normalize_pdf/normalize_image) use real pikepdf/
Pillow against small in-memory fixtures — no network. Orchestration tests
use a fake NormalizeStorage seam, same pattern as Stages 0.5/0.6/1.1.
"""
import gc
import io
import os

import pikepdf
import psutil
import pytest
from PIL import Image

from app.ingest.normalize import (
    MAX_IMAGE_DIMENSION,
    NormalizeError,
    _decode_image,
    normalize_image,
    normalize_pdf,
    run_normalize_job,
)
from app.ingest import normalize as normalize_module


# --- fixtures --------------------------------------------------------------


def _make_pdf_bytes(*, compress: bool, pages: int = 3) -> bytes:
    pdf = pikepdf.new()
    # Blank pages have no content stream to compress — normalization can
    # only add overhead to those. Give every page a real, highly
    # redundant content stream (repeated draw operators) so there's
    # something genuine to shrink.
    content = (b"1 0 0 RG 10 10 100 100 re S\n") * 2000
    for _ in range(pages):
        page = pdf.add_blank_page(page_size=(612, 792))
        pdf.pages[-1]["/Contents"] = pdf.make_stream(content)
        _ = page
    out = io.BytesIO()
    pdf.save(
        out,
        compress_streams=compress,
        object_stream_mode=pikepdf.ObjectStreamMode.disable if not compress else pikepdf.ObjectStreamMode.generate,
    )
    return out.getvalue()


def _make_jpeg_bytes(size: tuple[int, int], *, quality: int = 90) -> bytes:
    # A smooth gradient — realistic-ish photo content, cheap to encode
    # (unlike random noise, which makes JPEGs huge and slow to generate).
    img = Image.new("RGB", size)
    pixels = img.load()
    w, h = size
    for x in range(0, w, 4):
        for y in range(0, h, 4):
            color = ((x * 255) // w, (y * 255) // h, 128)
            for dx in range(4):
                for dy in range(4):
                    if x + dx < w and y + dy < h:
                        pixels[x + dx, y + dy] = color
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality)
    return out.getvalue()


# --- normalize_pdf -----------------------------------------------------------


def test_normalize_pdf_output_is_meaningfully_smaller():
    original = _make_pdf_bytes(compress=False, pages=5)
    normalized = normalize_pdf(original)
    assert len(normalized) < len(original) * 0.9, (
        f"expected meaningful shrink, got {len(original)} -> {len(normalized)}"
    )


def test_normalize_pdf_output_is_still_a_valid_pdf():
    original = _make_pdf_bytes(compress=False)
    normalized = normalize_pdf(original)
    with pikepdf.open(io.BytesIO(normalized)) as pdf:
        assert len(pdf.pages) == 3


def test_normalize_pdf_corrupt_input_raises_specific_error():
    corrupt = b"%PDF-1.7\n" + b"not a real pdf structure" * 20
    with pytest.raises(NormalizeError) as exc_info:
        normalize_pdf(corrupt)
    assert exc_info.value.code == "corrupt_pdf"


# --- normalize_image ---------------------------------------------------------


def test_normalize_image_output_is_webp_and_meaningfully_smaller():
    original = _make_jpeg_bytes((3000, 2000), quality=95)
    normalized, out_mime = normalize_image(original, "image/jpeg")
    assert out_mime == "image/webp"
    assert len(normalized) < len(original) * 0.7, (
        f"expected meaningful shrink, got {len(original)} -> {len(normalized)}"
    )
    result_img = Image.open(io.BytesIO(normalized))
    assert result_img.format == "WEBP"


def test_normalize_image_resizes_to_bounded_dimension():
    original = _make_jpeg_bytes((6000, 4000))
    normalized, _ = normalize_image(original, "image/jpeg")
    result_img = Image.open(io.BytesIO(normalized))
    assert max(result_img.size) <= MAX_IMAGE_DIMENSION


def test_normalize_image_corrupt_input_raises_specific_error():
    corrupt = b"not an image at all" * 20
    with pytest.raises(NormalizeError) as exc_info:
        normalize_image(corrupt, "image/jpeg")
    assert exc_info.value.code == "corrupt_image"


# --- draft-mode decode actually engages (the real point of Stage 1.2) ------


def test_draft_mode_produces_a_smaller_decode_target_than_source():
    # A >4000px source, per the exit criteria's literal wording.
    original = _make_jpeg_bytes((4096, 4096), quality=85)

    decoded = _decode_image(original, "image/jpeg")
    assert decoded.size != (4096, 4096), (
        "draft() left the decode target at full source resolution — "
        "not engaged, or Pillow silently declined it"
    )
    assert max(decoded.size) < 4096


def _rss_bytes() -> int:
    return psutil.Process(os.getpid()).memory_info().rss


def test_draft_mode_decode_uses_meaningfully_less_peak_memory():
    # tracemalloc only tracks Python-heap allocations — Pillow's decoded
    # pixel buffer is allocated in native code (via libjpeg) and is
    # invisible to it. Real process RSS is what actually matters for the
    # 512MB Render ceiling, so that's what this measures.
    original = _make_jpeg_bytes((4096, 4096), quality=85)

    gc.collect()
    before_full = _rss_bytes()
    img_no_draft = Image.open(io.BytesIO(original))
    img_no_draft.load()  # full-resolution decode, draft() never called
    full_delta = _rss_bytes() - before_full
    img_no_draft.close()
    del img_no_draft
    gc.collect()

    before_draft = _rss_bytes()
    img_draft = _decode_image(original, "image/jpeg")  # engages draft()
    draft_delta = _rss_bytes() - before_draft
    img_draft.close()

    assert draft_delta < full_delta * 0.6, (
        f"draft-mode decode used {draft_delta} bytes RSS vs {full_delta} "
        "for a full decode — expected a meaningful reduction, draft-mode "
        "may not actually be engaging"
    )


def test_png_has_no_draft_equivalent_but_still_gets_resized():
    # Pillow's draft() is documented JPEG/MPO-only — PNG decodes at full
    # resolution regardless. Stage 1.2 still normalizes it (resize +
    # re-encode), just without the decode-time RAM benefit.
    img = Image.new("RGB", (5000, 3000), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    normalized, out_mime = normalize_image(buf.getvalue(), "image/png")
    assert out_mime == "image/webp"
    result_img = Image.open(io.BytesIO(normalized))
    assert max(result_img.size) <= MAX_IMAGE_DIMENSION


# --- orchestration (run_normalize_job) --------------------------------------


class _FakeNormalizeStorage:
    def __init__(self, *, mime: str, original_content: bytes):
        self.mime = mime
        self.original_content = original_content
        self.uploaded = None
        self.marked_normalized = None
        self.marked_failed = None

    async def get_document(self, *, user_jwt, document_id):
        return {
            "id": document_id,
            "user_id": "11111111-1111-1111-1111-111111111111",
            "mime": self.mime,
            "original_storage_path": f"u/{document_id}/original.bin",
        }

    async def download_original(self, *, user_jwt, path):
        return self.original_content

    async def upload_indexed(self, *, user_jwt, user_id, document_id, ext, content, mime):
        path = f"{user_id}/{document_id}/indexed.{ext}"
        self.uploaded = (path, mime, len(content))
        return path

    async def mark_normalized(self, *, user_jwt, document_id, storage_path):
        self.marked_normalized = (document_id, storage_path)

    async def mark_failed(self, *, user_jwt, document_id, error_code):
        self.marked_failed = (document_id, error_code)


@pytest.fixture(autouse=True)
def _reset_storage():
    yield
    normalize_module.set_normalize_storage(normalize_module.SupabaseNormalizeStorage())


@pytest.mark.asyncio
async def test_run_normalize_job_pdf_happy_path():
    original = _make_pdf_bytes(compress=False)
    storage = _FakeNormalizeStorage(mime="application/pdf", original_content=original)
    normalize_module.set_normalize_storage(storage)

    await run_normalize_job(user_jwt="t", document_id="doc-1")

    assert storage.uploaded is not None
    path, mime, _size = storage.uploaded
    assert path.endswith("/indexed.pdf")
    assert mime == "application/pdf"
    assert storage.marked_normalized == ("doc-1", path)
    assert storage.marked_failed is None


@pytest.mark.asyncio
async def test_run_normalize_job_image_happy_path():
    original = _make_jpeg_bytes((1000, 800))
    storage = _FakeNormalizeStorage(mime="image/jpeg", original_content=original)
    normalize_module.set_normalize_storage(storage)

    await run_normalize_job(user_jwt="t", document_id="doc-2")

    path, mime, _size = storage.uploaded
    assert path.endswith("/indexed.webp")
    assert mime == "image/webp"
    assert storage.marked_normalized == ("doc-2", path)


@pytest.mark.asyncio
async def test_run_normalize_job_corrupt_pdf_marks_failed_not_hangs_or_crashes():
    corrupt = b"%PDF-1.7\n" + b"garbage" * 50
    storage = _FakeNormalizeStorage(mime="application/pdf", original_content=corrupt)
    normalize_module.set_normalize_storage(storage)

    await run_normalize_job(user_jwt="t", document_id="doc-3")

    assert storage.uploaded is None
    assert storage.marked_normalized is None
    assert storage.marked_failed == ("doc-3", "corrupt_pdf")


@pytest.mark.asyncio
async def test_normalize_concurrency_is_serialized():
    # Non-negotiable per CLAUDE.md's memory governance guardrails — two
    # normalize jobs must never run their heavy step at the same time.
    import asyncio

    order = []

    class _SlowStorage(_FakeNormalizeStorage):
        async def download_original(self, *, user_jwt, path):
            order.append(("start", path))
            await asyncio.sleep(0.05)
            order.append(("end", path))
            return self.original_content

    storage_a = _SlowStorage(mime="application/pdf", original_content=_make_pdf_bytes(compress=False))
    storage_b = _SlowStorage(mime="application/pdf", original_content=_make_pdf_bytes(compress=False))

    async def run_a():
        normalize_module.set_normalize_storage(storage_a)
        await run_normalize_job(user_jwt="t", document_id="doc-a")

    async def run_b():
        normalize_module.set_normalize_storage(storage_b)
        await run_normalize_job(user_jwt="t", document_id="doc-b")

    # Both jobs share the module-level lock regardless of which storage
    # instance is "current" at call time.
    await asyncio.gather(run_a(), run_b())
    # If concurrency were unguarded, both "start" events would appear
    # before either "end" event. Serialized: start, end, start, end.
    starts_before_first_end = order[:order.index(("end", order[0][1])) + 1]
    assert len([e for e in starts_before_first_end if e[0] == "start"]) == 1
