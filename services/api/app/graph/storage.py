"""Stage 2.1 — clustering job storage.

get_ready_documents_with_chunk_embeddings uses PostgREST's resource
embedding (`select=id,chunks(embedding)`) to fetch every ready
document's chunk embeddings in one request — not N+1 queries per
document, which matters once a user has hundreds of documents.

Caught live: PostgREST serializes a `halfvec` column as a JSON *string*
containing the vector's text representation (`"[-0.045,0.03,...]"`),
not a real JSON array of numbers — confirmed by a direct curl against
the live API after a real recluster run silently produced zero
clusters. Stage 1.5's retrieval never hit this, because its RPC
computes distance server-side and never returns raw embedding values
through PostgREST — this is the first code path that actually reads
one back. Each embedding string is parsed with json.loads before it
reaches numpy.

replace_graph inserts new cluster rows one at a time, not as a single
bulk INSERT — a bulk multi-row INSERT's returned rows are not
guaranteed by Postgres/PostgREST to come back in submission order, and
this code needs to map each numpy cluster index to its real database
id exactly. One request per cluster (there are only ever a few dozen)
avoids that ambiguity entirely instead of relying on an ordering
guarantee that doesn't actually exist. document_edges rows carry real
document ids on both ends already (no index-mapping problem), so those
go in as one bulk INSERT.
"""
import json
import os
from typing import Any

import httpx

from app.graph.cluster import ClusterAssignment, Edge


def _parse_embedding(raw: Any) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    return json.loads(raw)


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
                    parsed
                    for c in row.get("chunks", []) or []
                    if (parsed := _parse_embedding(c.get("embedding"))) is not None
                ],
            }
            for row in rows
        ]

    async def replace_graph(
        self,
        *,
        user_jwt: str,
        user_id: str,
        cluster_positions: list[tuple[float, float, float]],
        cluster_centroid_embeddings: list[list[float]],
        assignments: list[ClusterAssignment],
        edges: list[Edge],
    ) -> None:
        headers = self._headers(user_jwt)
        async with httpx.AsyncClient() as client:
            # document_clusters before clusters — it references clusters,
            # so it must be cleared first, not after. document_edges has
            # no such ordering constraint (both ends reference documents
            # directly) but is cleared alongside for the same full-replace
            # semantics.
            for table in ("document_clusters", "document_edges"):
                del_resp = await client.delete(
                    f"{self._supabase_url}/rest/v1/{table}",
                    headers=headers,
                    params={"user_id": f"eq.{user_id}"},
                )
                if del_resp.status_code >= 400:
                    raise GraphStorageError(f"delete_{table}_failed", del_resp.text)

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
            for (x, y, z), centroid_embedding in zip(cluster_positions, cluster_centroid_embeddings):
                insert_resp = await client.post(
                    f"{self._supabase_url}/rest/v1/clusters",
                    headers={
                        **headers,
                        "Content-Type": "application/json",
                        "Prefer": "return=representation",
                    },
                    json={
                        "user_id": user_id,
                        "centroid_x": x,
                        "centroid_y": y,
                        "centroid_z": z,
                        "centroid_embedding": centroid_embedding,
                    },
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

            if edges:
                edges_insert = await client.post(
                    f"{self._supabase_url}/rest/v1/document_edges",
                    headers={**headers, "Content-Type": "application/json"},
                    json=[
                        {
                            "document_id": e.document_id,
                            "neighbor_document_id": e.neighbor_document_id,
                            "user_id": user_id,
                            "distance": e.distance,
                            "rank": e.rank,
                        }
                        for e in edges
                    ],
                )
                if edges_insert.status_code >= 400:
                    raise GraphStorageError(
                        "insert_document_edges_failed", edges_insert.text
                    )

    async def get_nodes(self, *, user_jwt: str) -> list[dict[str, Any]]:
        """Every status=ready document, left-joined to its cluster
        position — a document uploaded since the last recluster still
        appears (cluster_id/x/y come back null), matching the exit
        criteria's "no stale/missing nodes after an upload" directly:
        node presence tracks documents.status live, not the last
        recluster snapshot the way edges/positions do."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/documents",
                headers=self._headers(user_jwt),
                params={
                    "status": "eq.ready",
                    "select": "id,title,document_clusters(cluster_id,distance,clusters(centroid_x,centroid_y,centroid_z))",
                },
            )
        if response.status_code >= 400:
            raise GraphStorageError("fetch_nodes_failed", response.text)
        nodes = []
        for row in response.json():
            dc = row.get("document_clusters")
            # PostgREST embeds a to-one relationship (document_clusters'
            # primary key is document_id, a genuine 1:1) as a single
            # object when present, not a list — confirmed live, not
            # assumed, same lesson as the halfvec string-vs-array find.
            cluster = (dc or {}).get("clusters") or {}
            nodes.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "cluster_id": (dc or {}).get("cluster_id"),
                    "x": cluster.get("centroid_x"),
                    "y": cluster.get("centroid_y"),
                    "z": cluster.get("centroid_z"),
                }
            )
        return nodes

    async def get_edges(self, *, user_jwt: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/document_edges",
                headers=self._headers(user_jwt),
                params={"select": "document_id,neighbor_document_id,distance,rank"},
            )
        if response.status_code >= 400:
            raise GraphStorageError("fetch_edges_failed", response.text)
        return response.json()

    async def get_node_chunks(
        self, *, user_jwt: str, document_id: str
    ) -> list[dict[str, Any]] | None:
        """None if the document doesn't exist or isn't the caller's own
        (RLS already scopes the query — this just distinguishes "not
        found" from "found, zero chunks") vs. an empty list once it's
        confirmed to exist."""
        async with httpx.AsyncClient() as client:
            doc_resp = await client.get(
                f"{self._supabase_url}/rest/v1/documents",
                headers=self._headers(user_jwt),
                params={"id": f"eq.{document_id}", "select": "id"},
            )
            if doc_resp.status_code >= 400:
                raise GraphStorageError("fetch_document_failed", doc_resp.text)
            if not doc_resp.json():
                return None

            chunks_resp = await client.get(
                f"{self._supabase_url}/rest/v1/chunks",
                headers=self._headers(user_jwt),
                params={
                    "document_id": f"eq.{document_id}",
                    "select": "id,ordinal,content,meta",
                    "order": "ordinal",
                },
            )
        if chunks_resp.status_code >= 400:
            raise GraphStorageError("fetch_chunks_failed", chunks_resp.text)
        return chunks_resp.json()

    async def get_clusters_with_centroids(self, *, user_jwt: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/clusters",
                headers=self._headers(user_jwt),
                params={"select": "id,centroid_embedding", "centroid_embedding": "not.is.null"},
            )
        if response.status_code >= 400:
            raise GraphStorageError("fetch_clusters_failed", response.text)
        return [
            {"id": row["id"], "centroid_embedding": _parse_embedding(row["centroid_embedding"])}
            for row in response.json()
        ]

    async def count_incremental_placements(self, *, user_jwt: str) -> int:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/document_clusters",
                headers=self._headers(user_jwt),
                params={"select": "document_id", "placement_method": "eq.incremental"},
            )
        if response.status_code >= 400:
            raise GraphStorageError("count_incremental_failed", response.text)
        return len(response.json())

    async def get_document_chunk_embeddings(
        self, *, user_jwt: str, document_id: str
    ) -> list[list[float]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._supabase_url}/rest/v1/chunks",
                headers=self._headers(user_jwt),
                params={"document_id": f"eq.{document_id}", "select": "embedding"},
            )
        if response.status_code >= 400:
            raise GraphStorageError("fetch_document_chunks_failed", response.text)
        return [
            parsed
            for row in response.json()
            if (parsed := _parse_embedding(row.get("embedding"))) is not None
        ]

    async def insert_incremental_assignment(
        self,
        *,
        user_jwt: str,
        user_id: str,
        document_id: str,
        cluster_id: str,
        distance: float,
    ) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._supabase_url}/rest/v1/document_clusters",
                headers={**self._headers(user_jwt), "Content-Type": "application/json"},
                json={
                    "document_id": document_id,
                    "cluster_id": cluster_id,
                    "user_id": user_id,
                    "distance": distance,
                    "placement_method": "incremental",
                },
            )
        if response.status_code >= 400:
            raise GraphStorageError("insert_incremental_assignment_failed", response.text)
