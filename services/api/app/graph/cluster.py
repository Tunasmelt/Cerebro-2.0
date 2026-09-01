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
doesn't reshuffle the whole graph; that's explicitly out of scope here.
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


def project_2d(centroids: np.ndarray) -> np.ndarray:
    """PCA via SVD: center the centroids, project onto their top-2
    principal components. Returns (k, 2)."""
    k = centroids.shape[0]
    if k == 1:
        return np.zeros((1, 2))
    mean = centroids.mean(axis=0)
    centered = centroids - mean
    _u, _s, vt = np.linalg.svd(centered, full_matrices=False)
    projected = centered @ vt[:2].T
    if projected.shape[1] < 2:
        # Fewer than 2 non-trivial directions (e.g. k=2 clusters can
        # only separate along 1 axis) — pad with zeros rather than error.
        projected = np.hstack(
            [projected, np.zeros((projected.shape[0], 2 - projected.shape[1]))]
        )
    return projected


@dataclass
class ClusterAssignment:
    document_id: str
    cluster_index: int
    distance: float


@dataclass
class ClusterResult:
    cluster_positions: list[tuple[float, float]]  # index-aligned with cluster labels
    assignments: list[ClusterAssignment]


def cluster_documents(
    documents: list[dict[str, Any]], *, seed: int = 0
) -> ClusterResult:
    """documents: [{"id": str, "chunk_embeddings": list[list[float]]}, ...] —
    only documents with at least one chunk embedding are clusterable;
    callers should already have filtered to status=ready documents."""
    clusterable = [d for d in documents if d["chunk_embeddings"]]
    if not clusterable:
        return ClusterResult(cluster_positions=[], assignments=[])

    centroids_by_doc = np.array(
        [compute_document_centroid(d["chunk_embeddings"]) for d in clusterable]
    )
    k = choose_k(len(clusterable))
    labels, cluster_centroids = kmeans(centroids_by_doc, k, seed=seed)
    positions = project_2d(cluster_centroids)

    assignments = [
        ClusterAssignment(
            document_id=doc["id"],
            cluster_index=int(label),
            distance=float(np.linalg.norm(centroids_by_doc[i] - cluster_centroids[label])),
        )
        for i, (doc, label) in enumerate(zip(clusterable, labels))
    ]
    return ClusterResult(
        cluster_positions=[(float(x), float(y)) for x, y in positions],
        assignments=assignments,
    )


class GraphStorage(Protocol):
    async def get_ready_documents_with_chunk_embeddings(
        self, *, user_jwt: str
    ) -> list[dict[str, Any]]: ...
    async def replace_clusters(
        self,
        *,
        user_jwt: str,
        user_id: str,
        cluster_positions: list[tuple[float, float]],
        assignments: list[ClusterAssignment],
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
        await storage.replace_clusters(
            user_jwt=user_jwt,
            user_id=user_id,
            cluster_positions=result.cluster_positions,
            assignments=result.assignments,
        )
        return len(result.assignments)
    except Exception:
        logger.exception("run_clustering_job failed for user %s", user_id)
        return -1
