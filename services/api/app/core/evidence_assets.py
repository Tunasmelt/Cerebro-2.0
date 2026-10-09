"""Private evidence-bucket lifecycle helpers."""
from __future__ import annotations

import httpx


async def delete_evidence_objects(
    client: httpx.AsyncClient, *, supabase_url: str, headers: dict[str, str], prefix: str
) -> bool:
    """Delete every object below a document prefix in bounded batches."""
    while True:
        listed = await client.post(
            f"{supabase_url}/storage/v1/object/list/evidence",
            headers=headers,
            json={"prefix": prefix, "limit": 1000, "offset": 0, "sortBy": {"column": "name", "order": "asc"}},
        )
        if listed.status_code >= 400:
            return False
        names = [row.get("name") for row in listed.json() if row.get("name")]
        if not names:
            return True
        paths = [f"{prefix}/{name}" for name in names]
        deleted = await client.request(
            "DELETE",
            f"{supabase_url}/storage/v1/object/evidence",
            headers=headers,
            json={"prefixes": paths},
        )
        if deleted.status_code >= 400:
            return False
        if len(names) < 1000:
            return True
