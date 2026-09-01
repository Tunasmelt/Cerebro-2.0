"""Stage 2.1 — clustering job storage.

get_ready_documents_with_chunk_embeddings uses PostgREST's resource
embedding (`select=id,chunks(embedding)`) to fetch every ready
document's chunk embeddings in one request — not N+1 queries per
document, which matters once a user has hundreds of documents.

replace_clusters inserts new cluster rows one at a time, not as a
single bulk INSERT — a bulk multi-row INSERT's returned rows are not
guaranteed by Postgres/PostgREST to come back in submission order, and
this code needs to map each numpy cluster index to its real database
id exactly. One request per cluster (there are only ever a few dozen)
avoids that ambiguity entirely instead of relying on an ordering
guarantee that doesn't actually exist.
"""
import os
from typing import Any

import httpx

from app.graph.cluster import ClusterAssignment


class GraphStorageError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class SupabaseGraphStorage:
    def __init__(self) -> None:
        self._supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self._anon_key = os.environ.get("SUPABASE_ANON_KEY", "")

    def _headers(self, user_jwt: str) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {user_jwt}"}

    async def get_ready_documents_with_chunk_embeddings(
        self, *, user_jwt: str
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/documents",
                headers=self._headers(user_jwt),
                params={"status": "eq.ready", "select": "id,chunks(embedding)"},
            )
        if response.status_code >= 400:
            raise GraphStorageError("fetch_documents_failed", response.text)
        rows = response.json()
        return [
            {
                "id": row["id"],
                "chunk_embeddings": [
                    c["embedding"]
                    for c in row.get("chunks", []) or []
                    if c.get("embedding") is not None
                ],
            }
            for row in rows
        ]

    async def replace_clusters(
        self,
        *,
        user_jwt: str,
        user_id: str,
        cluster_positions: list[tuple[float, float]],
        assignments: list[ClusterAssignment],
    ) -> None:
        headers = self._headers(user_jwt)
        async with httpx.AsyncClient() as client:
            # document_clusters first — it references clusters, so it
            # must go before clusters is cleared, not after.
            del_dc = await client.delete(
                f"{self._supabase_url}/rest/v1/document_clusters",
                headers=headers,
                params={"user_id": f"eq.{user_id}"},
            )
            if del_dc.status_code >= 400:
                raise GraphStorageError("delete_document_clusters_failed", del_dc.text)

            del_c = await client.delete(
                f"{self._supabase_url}/rest/v1/clusters",
                headers=headers,
                params={"user_id": f"eq.{user_id}"},
            )
            if del_c.status_code >= 400:
                raise GraphStorageError("delete_clusters_failed", del_c.text)

            if not cluster_positions:
                return

            cluster_ids: list[str] = []
            for x, y in cluster_positions:
                insert_resp = await client.post(
                    f"{self._supabase_url}/rest/v1/clusters",
                    headers={
                        **headers,
                        "Content-Type": "application/json",
                        "Prefer": "return=representation",
                    },
                    json={"user_id": user_id, "centroid_x": x, "centroid_y": y},
                )
                if insert_resp.status_code >= 400:
                    raise GraphStorageError("insert_cluster_failed", insert_resp.text)
                cluster_ids.append(insert_resp.json()[0]["id"])

            dc_insert = await client.post(
                f"{self._supabase_url}/rest/v1/document_clusters",
                headers={**headers, "Content-Type": "application/json"},
                json=[
                    {
                        "document_id": a.document_id,
                        "cluster_id": cluster_ids[a.cluster_index],
                        "user_id": user_id,
                        "distance": a.distance,
                    }
                    for a in assignments
                ],
            )
            if dc_insert.status_code >= 400:
                raise GraphStorageError("insert_document_clusters_failed", dc_insert.text)
