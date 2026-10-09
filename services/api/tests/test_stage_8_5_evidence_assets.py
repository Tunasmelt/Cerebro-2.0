import json

import httpx
import pytest

from app.core.evidence_assets import delete_evidence_objects


@pytest.mark.asyncio
async def test_evidence_cleanup_lists_and_deletes_exact_object_paths():
    requests = []

    async def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path.endswith("/list/evidence"):
            return httpx.Response(200, json=[{"name": "page-1.webp"}, {"name": "page-2.webp"}])
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        deleted = await delete_evidence_objects(
            client, supabase_url="https://db.example", headers={}, prefix="user/doc"
        )

    assert deleted is True
    body = json.loads(requests[1].content)
    assert body["prefixes"] == ["user/doc/page-1.webp", "user/doc/page-2.webp"]


@pytest.mark.asyncio
async def test_evidence_cleanup_aborts_when_listing_fails():
    async def handler(_request: httpx.Request):
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert not await delete_evidence_objects(
            client, supabase_url="https://db.example", headers={}, prefix="user/doc"
        )
