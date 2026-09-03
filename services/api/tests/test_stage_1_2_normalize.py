"""Stage 1.2 — normalize pipeline.

Exit criteria: PDFs pass through pikepdf structural optimization; images
pass through draft-mode decode and WebP re-encode; both land in
`indexed`, originals untouched in `originals`.

Pure-function tests (normalize_pdf/normalize_image) use real pikepdf/
Pillow against small in-memory fixtures — no network. Orchestration tests
use a fake NormalizeStorage seam, same pattern as Stages 0.5/0.6/1.1.
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pikepdf
import psutil
import pytest
from PIL import Image

from app.ingest.normalize import (
    MAX_IMAGE_DIMENSION,
    MAX_NON_JPEG_DECODE_PIXELS,
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


# This file's own pytest process runs 400+ other tests before this one —
# by the time this test runs, glibc's malloc arena on Linux CI typically
# already holds freed-but-still-resident pages from earlier tests' large
# allocations (PDF/image fixtures elsewhere in this suite). A new
# allocation the same size or smaller than that free capacity gets
# satisfied from already-resident memory without the OS ever growing
# RSS, so `psutil`'s before/after delta reads 0 for *both* the full and
# draft-mode decode regardless of what Pillow actually did — a false
# "draft-mode isn't engaging" failure with no relationship to the real
# code under test. Confirmed live: this started failing consistently in
# CI (0 bytes RSS reported for both) while remaining 424/424 clean
# locally on every run — a shared-process artifact of *this* test's
# measurement approach, not a code regression (nothing in this file's
# own image-decode logic changed). glibc's allocator behavior here also
# genuinely differs from Windows' allocator, which is why local runs
# never reproduced it.
#
# Fix: run the actual before/after measurement in a fresh subprocess
# instead of this shared pytest process. A brand-new interpreter has no
# prior allocation history to be satisfied from, so RSS deltas measure
# real page growth again — the same real invariant (draft-mode decode
# uses meaningfully less peak memory), just measured somewhere its
# result can't be contaminated by unrelated tests that happened to run
# first.
_SUBPROCESS_SCRIPT = """
import gc, io, json, os, sys
import psutil
from PIL import Image
from app.ingest.normalize import _decode_image

def rss():
    return psutil.Process(os.getpid()).memory_info().rss

with open(sys.argv[1], "rb") as f:
    original = f.read()

gc.collect()
before_full = rss()
img_no_draft = Image.open(io.BytesIO(original))
img_no_draft.load()  # full-resolution decode, draft() never called
full_delta = rss() - before_full
img_no_draft.close()
del img_no_draft
gc.collect()

before_draft = rss()
img_draft = _decode_image(original, "image/jpeg")  # engages draft()
draft_delta = rss() - before_draft
img_draft.close()

print(json.dumps({"full_delta": full_delta, "draft_delta": draft_delta}))
"""


def test_draft_mode_decode_uses_meaningfully_less_peak_memory(tmp_path):
    # tracemalloc only tracks Python-heap allocations — Pillow's decoded
    # pixel buffer is allocated in native code (via libjpeg) and is
    # invisible to it. Real process RSS is what actually matters for the
    # 512MB Render ceiling, so that's what this measures — in a fresh
    # subprocess, see _SUBPROCESS_SCRIPT's comment above for why.
    original = _make_jpeg_bytes((4096, 4096), quality=85)
    image_path = tmp_path / "fixture.jpg"
    image_path.write_bytes(original)

    services_api_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SCRIPT, str(image_path)],
        cwd=services_api_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"subprocess failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    deltas = json.loads(result.stdout.strip().splitlines()[-1])
    full_delta = deltas["full_delta"]
    draft_delta = deltas["draft_delta"]

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


# --- Stage 7.6: PNG/WebP pixel cap (no draft-mode decode to protect them) ----


def test_oversized_png_is_rejected_before_load_with_a_specific_error():
    width, height = 6500, 4000  # 26,000,000 px > MAX_NON_JPEG_DECODE_PIXELS
    assert width * height > MAX_NON_JPEG_DECODE_PIXELS
    img = Image.new("RGB", (width, height), color=(1, 2, 3))  # solid
    # color so PNG encoding stays cheap despite the pixel count
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    with pytest.raises(NormalizeError) as exc_info:
        normalize_image(buf.getvalue(), "image/png")
    assert exc_info.value.code == "image_too_large"


def test_oversized_webp_is_also_rejected_by_the_same_cap():
    width, height = 6500, 4000
    img = Image.new("RGB", (width, height), color=(4, 5, 6))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")

    with pytest.raises(NormalizeError) as exc_info:
        normalize_image(buf.getvalue(), "image/webp")
    assert exc_info.value.code == "image_too_large"


def test_png_under_the_pixel_cap_is_still_accepted():
    img = Image.new("RGB", (1000, 1000), color=(7, 8, 9))  # well under cap
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    normalized, out_mime = normalize_image(buf.getvalue(), "image/png")
    assert out_mime == "image/webp"


def test_jpeg_is_never_subject_to_the_non_jpeg_pixel_cap():
    # Same pixel count that rejects a PNG/WebP above — JPEG has draft()
    # to protect it instead, so this cap must not apply to it at all.
    width, height = 6500, 4000
    assert width * height > MAX_NON_JPEG_DECODE_PIXELS
    img = Image.new("RGB", (width, height), color=(10, 11, 12))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")

    normalized, out_mime = normalize_image(buf.getvalue(), "image/jpeg")
    assert out_mime == "image/webp"


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
async def test_run_normalize_job_text_uploads_with_explicit_utf8_charset():
    """A bare "text/plain"/"text/markdown" Content-Type left the browser
    guessing an encoding (windows-1252 in practice) when a signed URL was
    opened directly — every UTF-8 multi-byte character rendered as
    mojibake. The uploaded bytes were always correct UTF-8; only the
    header describing them was missing the charset."""
    original = "Cerebro — architecture notes".encode()
    storage = _FakeNormalizeStorage(mime="text/plain", original_content=original)
    normalize_module.set_normalize_storage(storage)

    await run_normalize_job(user_jwt="t", document_id="doc-txt")

    _path, mime, _size = storage.uploaded
    assert mime == "text/plain; charset=utf-8"


@pytest.mark.asyncio
async def test_run_normalize_job_markdown_uploads_with_explicit_utf8_charset():
    original = "# Heading—with an em dash".encode()
    storage = _FakeNormalizeStorage(mime="text/markdown", original_content=original)
    normalize_module.set_normalize_storage(storage)

    await run_normalize_job(user_jwt="t", document_id="doc-md")

    path, mime, _size = storage.uploaded
    assert path.endswith("/indexed.md")
    assert mime == "text/markdown; charset=utf-8"
    assert storage.marked_normalized == ("doc-md", path)


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
