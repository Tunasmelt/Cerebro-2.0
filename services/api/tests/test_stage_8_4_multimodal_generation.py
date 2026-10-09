import pytest

from app.retrieve.multimodal import MAX_VISUAL_BYTES, build_multimodal_input
from app.retrieve.retrieve import RetrievedChunk


def _chunk(index: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c{index}", document_id="doc", ordinal=index, content="chart",
        meta={"region_id": f"r{index}", "region_type": "chart", "page": index + 1,
              "bbox": [0, 0, 1, 1], "representation_type": "visual"},
        relevance_score=1,
    )


@pytest.mark.asyncio
async def test_visual_payload_is_ordered_capped_and_citation_anchored():
    calls = []

    async def load(region_id):
        calls.append(region_id)
        return b"x" * 100, "image/webp"

    blocks = await build_multimodal_input("Explain", [_chunk(i) for i in range(6)], load)
    images = [block for block in blocks if block["type"] == "image"]
    assert len(images) == 4
    assert calls == ["r0", "r1", "r2", "r3"]
    for image in images:
        previous = blocks[blocks.index(image) - 1]
        assert previous["type"] == "text"
        assert "[[chunk:c" in previous["text"]


@pytest.mark.asyncio
async def test_visual_byte_budget_stops_before_oversized_crop():
    async def load(_region_id):
        return b"x" * (MAX_VISUAL_BYTES + 1), "image/webp"

    assert await build_multimodal_input("Explain", [_chunk(0)], load) == [
        {"type": "text", "text": "Explain"}
    ]
