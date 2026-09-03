"""Stage 1.3 — extract & chunk.

Exit criteria: text, PDFs, and images produce chunks with correct
document_id, ordinal, and meta (page/bbox where applicable).

Per conversation record: pdfplumber for PDF text extraction (no library
was specified in the docs — pikepdf is structure-only). Image tiling
operates on the ORIGINAL (from `originals`), not the Stage 1.2-resized
indexed copy, since everything in `indexed` is already ≤2048px and would
never register as "oversized" by the time this stage runs.
"""
import io

import pikepdf
import pytest
from PIL import Image

from app.ingest import extract as extract_module
from app.ingest.extract import (
    IMAGE_TILE_THRESHOLD,
    ExtractError,
    chunk_text,
    extract_image_chunks,
    extract_pdf_chunks,
    extract_text_chunks,
    run_extract_job,
)

# --- fixtures ----------------------------------------------------------------


def _make_pdf_with_page_text(pages_text: list[str]) -> bytes:
    pdf = pikepdf.new()
    for _ in pages_text:
        pdf.add_blank_page(page_size=(612, 792))
    out = io.BytesIO()
    pdf.save(out)
    pdf_bytes = out.getvalue()

    # pikepdf can create pages but writing real extractable text streams
    # by hand is fiddly — use pdfplumber's own dependency, reportlab-free
    # route: build via pikepdf content streams with a simple Tj operator
    # per page using the standard Helvetica base font (no font embedding
    # needed for the built-in PDF base-14 fonts).
    with pikepdf.open(io.BytesIO(pdf_bytes)) as doc:
        font = pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica,
        )
        for page, text in zip(doc.pages, pages_text):
            page["/Resources"] = pikepdf.Dictionary(
                Font=pikepdf.Dictionary(F1=doc.make_indirect(font))
            )
            content = f"BT /F1 24 Tf 50 700 Td ({text}) Tj ET".encode()
            page["/Contents"] = doc.make_stream(content)
        result = io.BytesIO()
        doc.save(result)
        return result.getvalue()


def _make_image_bytes(size: tuple[int, int]) -> bytes:
    img = Image.new("RGB", size, color=(100, 150, 200))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


# --- chunk_text ----------------------------------------------------------------


def test_chunk_text_produces_a_stable_expected_count_for_a_known_fixture():
    # Regression test — fails loudly if the chunking parameters change
    # unexpectedly. 2500 chars at size=1000/overlap=100 -> 3 chunks
    # (0-1000, 900-1900, 1800-2500).
    text = "word " * 500  # 2500 chars
    chunks = chunk_text(text, chunk_size=1000, overlap=100)
    assert len(chunks) == 3


def test_chunk_text_short_input_produces_one_chunk():
    chunks = chunk_text("short text", chunk_size=1000, overlap=100)
    assert len(chunks) == 1
    assert chunks[0] == "short text"


def test_chunk_text_empty_input_produces_no_chunks():
    assert chunk_text("", chunk_size=1000, overlap=100) == []
    assert chunk_text("   \n  ", chunk_size=1000, overlap=100) == []


# --- chunk_text boundary awareness (Stage 7.1) ---------------------------------


def _prose(sentence_count: int) -> str:
    # Varied sentence lengths so cut points don't land on a convenient
    # repeating stride the way "word " * n does.
    return " ".join(
        f"Sentence number {i} carries {'a bit ' * (i % 4)}of filler text."
        for i in range(sentence_count)
    )


def test_chunk_text_never_splits_a_word_across_chunks():
    # The actual Stage 7.1 exit criterion: for realistic prose, no chunk
    # may start or end mid-word.
    text = _prose(300)
    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    assert len(chunks) > 1  # otherwise this proves nothing
    for chunk in chunks:
        assert chunk == chunk.strip()
        start = text.index(chunk)
        end = start + len(chunk)
        # A chunk edge is legal only at a document edge or against
        # whitespace in the source — never in the middle of a token.
        assert start == 0 or text[start - 1].isspace()
        assert end == len(text) or text[end].isspace()


def test_chunk_text_prefers_a_paragraph_break_over_a_word_boundary():
    # The paragraph break sits inside the search window (last 20% of the
    # 1000-char target), so it should win over any later word boundary.
    head = "a" * 850 + " tail words here"
    text = head + "\n\n" + "b" * 1200
    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    assert chunks[0] == head


def test_chunk_text_prefers_a_sentence_end_over_a_mid_sentence_word_boundary():
    # No paragraph break available, and the sentence end is followed by
    # plenty of later word boundaries still inside the window — the
    # sentence end must win anyway, on strength rather than position.
    head = "x" * 820 + " end of the sentence."
    text = head + " then plain words follow with no terminator at all " + "y" * 1200
    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    assert chunks[0] == head


def test_chunk_text_snaps_to_the_latest_boundary_in_the_window():
    # Among equally-strong boundaries, the one nearest the target size
    # wins — snapping back should cost as little chunk size as possible.
    text = "x" * 700 + " first. " + "y" * 100 + " second. " + "z" * 1200
    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    assert chunks[0].endswith("second.")


def test_chunk_text_hard_cuts_when_the_window_holds_no_boundary_at_all():
    # An unbreakable token (base64 blob, minified source, spaceless CJK)
    # must still chunk rather than loop or emit one giant chunk.
    text = "z" * 3000
    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(dict.fromkeys(chunks)) != ""  # produced real content


def test_chunk_text_loses_no_text_between_consecutive_chunks():
    # Boundary snapping must never open a gap — every character of the
    # source has to survive into at least one chunk.
    text = _prose(200)
    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    cursor = 0
    for chunk in chunks:
        found = text.index(chunk, max(0, cursor - 1000))
        assert found <= cursor, "gap between chunks — source text was dropped"
        cursor = found + len(chunk)
    assert cursor == len(text)


def test_chunk_text_terminates_when_overlap_exceeds_chunk_size():
    # Pathological caller input: without an explicit forward-progress
    # guarantee this loops forever.
    chunks = chunk_text(_prose(100), chunk_size=200, overlap=500)

    assert len(chunks) > 1


# --- extract_text_chunks -------------------------------------------------------


def test_extract_text_chunks_assigns_sequential_ordinals_and_empty_meta():
    chunks = extract_text_chunks("word " * 500)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(c.meta == {} for c in chunks)


# --- extract_pdf_chunks ----------------------------------------------------------


def test_extract_pdf_chunks_produces_chunks_in_correct_page_order():
    pdf_bytes = _make_pdf_with_page_text(["First page content", "Second page content", "Third page content"])
    chunks = extract_pdf_chunks(pdf_bytes)

    assert len(chunks) >= 3  # at least one chunk per page
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    pages_seen = [c.meta["page"] for c in chunks]
    assert pages_seen == sorted(pages_seen), "chunks must appear in page order"
    assert set(pages_seen) == {1, 2, 3}


def test_extract_pdf_chunks_corrupt_input_raises_specific_error():
    corrupt = b"%PDF-1.7\n" + b"not a real structure" * 20
    with pytest.raises(ExtractError) as exc_info:
        extract_pdf_chunks(corrupt)
    assert exc_info.value.code == "corrupt_pdf"


# --- extract_image_chunks --------------------------------------------------------


def test_oversized_image_is_tiled_with_distinct_bboxes():
    original = _make_image_bytes((IMAGE_TILE_THRESHOLD + 500, IMAGE_TILE_THRESHOLD + 500))
    chunks = extract_image_chunks(original)

    assert len(chunks) > 1, "an oversized image must produce more than one chunk"
    bboxes = [tuple(c.meta["bbox"]) for c in chunks]
    assert len(set(bboxes)) == len(bboxes), "every tile must have a distinct bbox"
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_oversized_image_tiles_cover_the_whole_image_without_gaps():
    w, h = IMAGE_TILE_THRESHOLD + 500, IMAGE_TILE_THRESHOLD + 200
    original = _make_image_bytes((w, h))
    chunks = extract_image_chunks(original)

    max_x = max(c.meta["bbox"][2] for c in chunks)
    max_y = max(c.meta["bbox"][3] for c in chunks)
    assert max_x == w
    assert max_y == h


def test_small_image_produces_a_single_chunk_with_whole_image_bbox():
    original = _make_image_bytes((800, 600))
    chunks = extract_image_chunks(original)
    assert len(chunks) == 1
    assert chunks[0].meta["bbox"] == [0, 0, 800, 600]


def test_extract_image_chunks_corrupt_input_raises_specific_error():
    with pytest.raises(ExtractError) as exc_info:
        extract_image_chunks(b"not an image" * 20)
    assert exc_info.value.code == "corrupt_image"


# --- orchestration (run_extract_job) -----------------------------------------


class _FakeExtractStorage:
    def __init__(
        self,
        *,
        mime: str,
        indexed_content: bytes = b"",
        original_content: bytes = b"",
        source: str = "upload",
        captured_text: str | None = None,
    ):
        self.mime = mime
        self.indexed_content = indexed_content
        self.original_content = original_content
        self.source = source
        self.captured_text = captured_text
        self.inserted_chunks = None
        self.marked_extracted = None
        self.marked_failed = None
        self.download_calls: list[str] = []

    async def get_document(self, *, user_jwt, document_id):
        return {
            "id": document_id,
            "user_id": "11111111-1111-1111-1111-111111111111",
            "mime": self.mime,
            "source": self.source,
            "captured_text": self.captured_text,
            "storage_path": f"u/{document_id}/indexed.bin",
            "original_storage_path": f"u/{document_id}/original.bin",
        }

    async def download_indexed(self, *, user_jwt, path):
        self.download_calls.append("indexed")
        return self.indexed_content

    async def download_original(self, *, user_jwt, path):
        self.download_calls.append("original")
        return self.original_content

    async def insert_chunks(self, *, user_jwt, document_id, user_id, chunks):
        self.inserted_chunks = chunks

    async def mark_extracted(self, *, user_jwt, document_id):
        self.marked_extracted = document_id

    async def mark_failed(self, *, user_jwt, document_id, error_code):
        self.marked_failed = (document_id, error_code)


@pytest.fixture(autouse=True)
def _reset_storage():
    yield
    extract_module.set_extract_storage(extract_module.SupabaseExtractStorage())


@pytest.mark.asyncio
async def test_run_extract_job_text_happy_path():
    storage = _FakeExtractStorage(mime="text/plain", indexed_content=b"word " * 500)
    extract_module.set_extract_storage(storage)

    result = await run_extract_job(user_jwt="t", document_id="doc-1")

    assert result is True
    assert storage.inserted_chunks is not None
    assert len(storage.inserted_chunks) > 0
    assert storage.marked_extracted == "doc-1"
    assert storage.marked_failed is None


@pytest.mark.asyncio
async def test_run_extract_job_markdown_uses_the_same_text_chunker():
    """text/markdown takes the exact same branch as text/plain — no
    markdown-aware parsing exists or is needed, the `#`/`*`/etc. syntax
    just chunks as ordinary text."""
    storage = _FakeExtractStorage(mime="text/markdown", indexed_content=b"# Heading\n\nword " * 200)
    extract_module.set_extract_storage(storage)

    result = await run_extract_job(user_jwt="t", document_id="doc-md")

    assert result is True
    assert storage.inserted_chunks is not None
    assert len(storage.inserted_chunks) > 0
    assert storage.marked_extracted == "doc-md"
    assert storage.marked_failed is None


@pytest.mark.asyncio
async def test_run_extract_job_pdf_happy_path():
    pdf_bytes = _make_pdf_with_page_text(["Alpha", "Beta"])
    storage = _FakeExtractStorage(mime="application/pdf", indexed_content=pdf_bytes)
    extract_module.set_extract_storage(storage)

    result = await run_extract_job(user_jwt="t", document_id="doc-2")

    assert result is True
    pages_seen = {c.meta["page"] for c in storage.inserted_chunks}
    assert pages_seen == {1, 2}


@pytest.mark.asyncio
async def test_run_extract_job_image_reads_from_original_not_indexed():
    small_original = _make_image_bytes((800, 600))
    storage = _FakeExtractStorage(
        mime="image/jpeg", indexed_content=b"not-a-real-image", original_content=small_original
    )
    extract_module.set_extract_storage(storage)

    result = await run_extract_job(user_jwt="t", document_id="doc-3")

    assert result is True
    assert storage.inserted_chunks[0].meta["bbox"] == [0, 0, 800, 600]


@pytest.mark.asyncio
async def test_run_extract_job_corrupt_pdf_marks_failed_not_hangs_or_crashes():
    storage = _FakeExtractStorage(mime="application/pdf", indexed_content=b"%PDF-1.7\ngarbage" * 20)
    extract_module.set_extract_storage(storage)

    result = await run_extract_job(user_jwt="t", document_id="doc-4")

    assert result is False
    assert storage.inserted_chunks is None
    assert storage.marked_extracted is None
    assert storage.marked_failed[0] == "doc-4"


# --- Stage 5.5: source == "capture" skips any storage download ------------------


@pytest.mark.asyncio
async def test_run_extract_job_for_a_capture_document_chunks_the_row_text_directly():
    storage = _FakeExtractStorage(
        mime="text/plain",
        source="capture",
        captured_text="word " * 500,
    )
    extract_module.set_extract_storage(storage)

    result = await run_extract_job(user_jwt="t", document_id="doc-5")

    assert result is True
    assert storage.inserted_chunks is not None
    assert len(storage.inserted_chunks) > 0
    # The whole point of Stage 5.5: no Storage object exists for a
    # capture document, so neither download method should ever be
    # called for one.
    assert storage.download_calls == []


@pytest.mark.asyncio
async def test_run_extract_job_for_a_capture_document_with_empty_text_produces_no_chunks():
    storage = _FakeExtractStorage(mime="text/plain", source="capture", captured_text="")
    extract_module.set_extract_storage(storage)

    result = await run_extract_job(user_jwt="t", document_id="doc-6")

    assert result is True
    assert storage.download_calls == []
