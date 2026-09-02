"""Stage 2.1 — clustering job.

k-means and the 2D projection are hand-rolled with numpy directly
rather than pulling in scikit-learn — CLAUDE.md's "no heavy transitive
deps" posture, and the problem is small enough (a few hundred
documents, 1024-dim vectors) not to need a full ML library. This mirrors
the project's Stage 1.8 experience with `ragas`: a heavy dependency
tree for one algorithm is a real cost, and here it's avoidable.

Document-level centroid vectors are mean-pooled from each document's
chunk embeddings on the fly (chunks.embedding already exists from Stage
1.4) — nothing new is stored per-document, only the final cluster
assignment.

k is chosen via a standard heuristic (round(sqrt(n/2))), not specified
anywhere in the docs — a reasonable, easy-to-retune default, same
category as retrieve.py's RRF_K/RELEVANCE_FLOOR.

This stage does a full re-cluster every run — every document's
centroid, all at once, k-means from scratch. Stage 2.5 adds incremental
nearest-centroid placement for new uploads so a single new document
doesn't reshuffle the whole graph.

Stage 2.5's placement uses each cluster's real 1024-dim centroid
(`clusters.centroid_embedding`), not the 2D PCA-projected position
(`centroid_x`/`centroid_y`) — the same "don't use the lossy projection
for real distance" principle as Stage 2.2's kNN edges. A new document
is assigned to its nearest existing cluster by real embedding distance
without moving that cluster's stored 2D position or touching any other
document's row — that's what makes "does not change the position of
unrelated existing nodes" true by construction, not by carefully not
breaking it. After INCREMENTAL_RECLUSTER_THRESHOLD documents have been
placed this way since the last full recluster, the next one triggers a
full recluster instead (which also resets the threshold, since every
row becomes a fresh 'kmeans' placement again).
"""
import logging
import math
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

logger = logging.getLogger(__name__)

MAX_KMEANS_ITERATIONS = 100


def compute_document_centroid(chunk_embeddings: list[list[float]]) -> np.ndarray:
    """Mean-pooled centroid of one document's chunk embeddings."""
    return np.mean(np.array(chunk_embeddings, dtype=np.float64), axis=0)


def choose_k(n_documents: int) -> int:
    if n_documents <= 1:
        return 1
    return max(1, round(math.sqrt(n_documents / 2)))


def _kmeans_plus_plus_init(
    vectors: np.ndarray, k: int, rng: np.random.Generator
) -> np.ndarray:
    n = vectors.shape[0]
    centroids = np.empty((k, vectors.shape[1]), dtype=np.float64)
    centroids[0] = vectors[rng.integers(0, n)]
    for i in range(1, k):
        nearest_dist = np.min(
            np.linalg.norm(vectors[:, None, :] - centroids[None, :i, :], axis=2),
            axis=1,
        )
        weights = nearest_dist**2
        total = weights.sum()
        next_idx = (
            rng.integers(0, n) if total == 0 else rng.choice(n, p=weights / total)
        )
        centroids[i] = vectors[next_idx]
    return centroids


def kmeans(
    vectors: np.ndarray,
    k: int,
    *,
    seed: int = 0,
    max_iterations: int = MAX_KMEANS_ITERATIONS,
) -> tuple[np.ndarray, np.ndarray]:
    """Lloyd's algorithm with k-means++ initialization, hand-rolled.
    Returns (labels, centroids). Deterministic given `seed` — a
    reproducible graph layout across recluster runs matters here, not
    just test determinism."""
    n = vectors.shape[0]
    k = min(k, n)
    rng = np.random.default_rng(seed)
    centroids = _kmeans_plus_plus_init(vectors, k, rng)

    labels = np.full(n, -1, dtype=np.int64)
    for iteration in range(max_iterations):
        distances = np.linalg.norm(vectors[:, None, :] - centroids[None, :, :], axis=2)
        new_labels = np.argmin(distances, axis=1)
        converged = iteration > 0 and np.array_equal(new_labels, labels)
        labels = new_labels
        if converged:
            break
        for i in range(k):
            members = vectors[labels == i]
            if len(members) > 0:
                centroids[i] = members.mean(axis=0)
    return labels, centroids


def project_3d(centroids: np.ndarray) -> np.ndarray:
    """PCA via SVD: center the centroids, project onto their top-3
    principal components. Returns (k, 3) — extended from the original
    2D projection (was project_2d) for the 3D graph rendering upgrade;
    same fallback logic, one dimension wider."""
    k = centroids.shape[0]
    if k == 1:
        return np.zeros((1, 3))
    mean = centroids.mean(axis=0)
    centered = centroids - mean
    _u, _s, vt = np.linalg.svd(centered, full_matrices=False)
    projected = centered @ vt[:3].T
    if projected.shape[1] < 3:
        # Fewer than 3 non-trivial directions (e.g. k=2 clusters can only
        # separate along 1 axis) — pad with zeros rather than error.
        projected = np.hstack(
            [projected, np.zeros((projected.shape[0], 3 - projected.shape[1]))]
        )
    return projected


@dataclass
class ClusterAssignment:
    document_id: str
    cluster_index: int
    distance: float


@dataclass
class Edge:
    document_id: str
    neighbor_document_id: str
    distance: float
    rank: int  # 1..NEIGHBORS_PER_DOCUMENT, nearest first


@dataclass
class ClusterResult:
    cluster_positions: list[tuple[float, float, float]]  # index-aligned with cluster labels
    cluster_centroid_embeddings: list[list[float]]  # index-aligned, real 1024-dim
    assignments: list[ClusterAssignment]
    edges: list[Edge]


NEIGHBORS_PER_DOCUMENT = 3  # per api-documentation.md's "3 nearest neighbors"


def compute_knn_edges(
    document_ids: list[str], centroids_by_doc: np.ndarray, *, k: int = NEIGHBORS_PER_DOCUMENT
) -> list[Edge]:
    """True nearest neighbors in embedding space (the real 1024-dim
    document centroids), not the lossy 2D projection — two documents can
    sit far apart in the PCA projection while still being genuinely
    close in the original space, especially once there are more than 2
    clusters and a 2D projection can't preserve every pairwise
    distance."""
    n = centroids_by_doc.shape[0]
    edges: list[Edge] = []
    for i in range(n):
        distances = np.linalg.norm(centroids_by_doc - centroids_by_doc[i], axis=1)
        distances[i] = np.inf  # exclude self
        nearest_indices = np.argsort(distances)[: min(k, n - 1)]
        for rank, j in enumerate(nearest_indices, start=1):
            edges.append(
                Edge(
                    document_id=document_ids[i],
                    neighbor_document_id=document_ids[j],
                    distance=float(distances[j]),
                    rank=rank,
                )
            )
    return edges


def cluster_documents(
    documents: list[dict[str, Any]], *, seed: int = 0
) -> ClusterResult:
    """documents: [{"id": str, "chunk_embeddings": list[list[float]]}, ...] —
    only documents with at least one chunk embedding are clusterable;
    callers should already have filtered to status=ready documents."""
    clusterable = [d for d in documents if d["chunk_embeddings"]]
    if not clusterable:
        return ClusterResult(
            cluster_positions=[], cluster_centroid_embeddings=[], assignments=[], edges=[]
        )

    centroids_by_doc = np.array(
        [compute_document_centroid(d["chunk_embeddings"]) for d in clusterable]
    )
    document_ids = [d["id"] for d in clusterable]

    k = choose_k(len(clusterable))
    labels, cluster_centroids = kmeans(centroids_by_doc, k, seed=seed)
    positions = project_3d(cluster_centroids)

    assignments = [
        ClusterAssignment(
            document_id=doc["id"],
            cluster_index=int(label),
            distance=float(np.linalg.norm(centroids_by_doc[i] - cluster_centroids[label])),
        )
        for i, (doc, label) in enumerate(zip(clusterable, labels))
    ]
    edges = (
        compute_knn_edges(document_ids, centroids_by_doc)
        if len(clusterable) > 1
        else []
    )
    return ClusterResult(
        cluster_positions=[(float(x), float(y), float(z)) for x, y, z in positions],
        cluster_centroid_embeddings=[c.tolist() for c in cluster_centroids],
        assignments=assignments,
        edges=edges,
    )


class GraphStorage(Protocol):
    async def get_ready_documents_with_chunk_embeddings(
        self, *, user_jwt: str
    ) -> list[dict[str, Any]]: ...
    async def replace_graph(
        self,
        *,
        user_jwt: str,
        user_id: str,
        cluster_positions: list[tuple[float, float, float]],
        cluster_centroid_embeddings: list[list[float]],
        assignments: list[ClusterAssignment],
        edges: list[Edge],
    ) -> None: ...
    async def get_nodes(self, *, user_jwt: str) -> list[dict[str, Any]]: ...
    async def get_edges(self, *, user_jwt: str) -> list[dict[str, Any]]: ...
    async def get_node_chunks(
        self, *, user_jwt: str, document_id: str
    ) -> list[dict[str, Any]] | None: ...
    async def get_clusters_with_centroids(
        self, *, user_jwt: str
    ) -> list[dict[str, Any]]: ...
    async def count_incremental_placements(self, *, user_jwt: str) -> int: ...
    async def get_document_chunk_embeddings(
        self, *, user_jwt: str, document_id: str
    ) -> list[list[float]]: ...
    async def insert_incremental_assignment(
        self,
        *,
        user_jwt: str,
        user_id: str,
        document_id: str,
        cluster_id: str,
        distance: float,
    ) -> None: ...


_storage: GraphStorage | None = None


def get_graph_storage() -> GraphStorage:
    global _storage
    if _storage is None:
        from app.graph.storage import SupabaseGraphStorage

        _storage = SupabaseGraphStorage()
    return _storage


def set_graph_storage(storage: GraphStorage) -> None:
    """Test seam — inject a fake storage client."""
    global _storage
    _storage = storage


async def run_clustering_job(*, user_jwt: str, user_id: str) -> int:
    """Returns the number of documents clustered, or -1 if the job
    failed. Full recompute every run (see module docstring) — safe to
    call repeatedly, e.g. after every embed job completes, since it
    always replaces the prior cluster set rather than accumulating.

    Runs as a FastAPI BackgroundTask (routes/graph.py) — no client is
    waiting on it, so a failure here has no natural place to surface
    except the logs. Caught live: a real failure (chunks.embedding
    coming back from PostgREST as a JSON string, not an array — see
    storage.py) produced *no* traceback in Render's logs at all, not
    even an unhandled-exception one — so this is now wrapped explicitly
    rather than trusted to the framework's default background-task
    exception handling."""
    try:
        storage = get_graph_storage()
        documents = await storage.get_ready_documents_with_chunk_embeddings(
            user_jwt=user_jwt
        )
        result = cluster_documents(documents)
        await storage.replace_graph(
            user_jwt=user_jwt,
            user_id=user_id,
            cluster_positions=result.cluster_positions,
            cluster_centroid_embeddings=result.cluster_centroid_embeddings,
            assignments=result.assignments,
            edges=result.edges,
        )
        return len(result.assignments)
    except Exception:
        logger.exception("run_clustering_job failed for user %s", user_id)
        return -1


# Reasonable, easy-to-retune default — not specified anywhere in the
# docs, same category as choose_k's heuristic and retrieve.py's RRF_K.
INCREMENTAL_RECLUSTER_THRESHOLD = 10


def find_nearest_cluster(
    document_centroid: np.ndarray, clusters: list[dict[str, Any]]
) -> tuple[str, float] | None:
    """clusters: [{"id": str, "centroid_embedding": list[float]}, ...].
    Returns (cluster_id, distance) for the nearest one, or None if
    `clusters` is empty. Pure function — no I/O, unit-testable without
    numpy fixtures baked into storage mocks."""
    if not clusters:
        return None
    best_id = clusters[0]["id"]
    best_distance = float("inf")
    for c in clusters:
        centroid = np.array(c["centroid_embedding"], dtype=np.float64)
        distance = float(np.linalg.norm(document_centroid - centroid))
        if distance < best_distance:
            best_distance = distance
            best_id = c["id"]
    return best_id, best_distance


async def place_new_document(
    *, user_jwt: str, user_id: str, document_id: str
) -> str:
    """Returns "unclustered" (no clusters exist yet to join — same state
    a document sits in before any full recluster has ever run),
    "incremental" (assigned to its nearest existing cluster, nothing
    else touched), or "full_recluster" (the incremental-placement
    threshold was hit, so a full recompute ran instead — which also
    places this document, as part of clustering every ready document).

    Runs as a background step after embed completes (documents.py) —
    same "no client waiting, log failures explicitly" reasoning as
    run_clustering_job."""
    try:
        storage = get_graph_storage()
        clusters = await storage.get_clusters_with_centroids(user_jwt=user_jwt)
        if not clusters:
            return "unclustered"

        incremental_count = await storage.count_incremental_placements(user_jwt=user_jwt)
        if incremental_count + 1 >= INCREMENTAL_RECLUSTER_THRESHOLD:
            await run_clustering_job(user_jwt=user_jwt, user_id=user_id)
            return "full_recluster"

        chunk_embeddings = await storage.get_document_chunk_embeddings(
            user_jwt=user_jwt, document_id=document_id
        )
        if not chunk_embeddings:
            return "unclustered"
        document_centroid = compute_document_centroid(chunk_embeddings)

        nearest = find_nearest_cluster(document_centroid, clusters)
        if nearest is None:
            return "unclustered"
        cluster_id, distance = nearest
        await storage.insert_incremental_assignment(
            user_jwt=user_jwt,
            user_id=user_id,
            document_id=document_id,
            cluster_id=cluster_id,
            distance=distance,
        )
        return "incremental"
    except Exception:
        logger.exception("place_new_document failed for document %s", document_id)
        return "unclustered"
