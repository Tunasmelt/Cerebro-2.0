"""Stage 2.1 — clustering job.

Exit criteria: background job assigns documents to clusters via numpy
k-means on document-level centroid vectors, projects centroids to 2D
via numpy SVD/PCA.

Tests:
- Deterministic fixture set of documents with known semantic groupings
  clusters as expected (documents about the same topic land in the same
  cluster more often than not).
- Job completes within an acceptable time bound for a 300-document seed
  set — timed, not estimated.

The 300-document timing test runs on this machine's CPU, not Render's
constrained 0.1 CPU free-tier instance — the bound here is generous
specifically because of that gap; the real number that matters is a
live timed run against production once real documents exist there
(same caveat as Gemini's local-vs-Render latency difference elsewhere
in this project).
"""
import time

import numpy as np
import pytest

from app.graph import cluster as cluster_module
from app.graph.cluster import (
    choose_k,
    cluster_documents,
    kmeans,
    project_2d,
    run_clustering_job,
)

EMBEDDING_DIM = 1024


def _seeded_random_unit_vectors(n: int, dim: int, *, seed: int, center: np.ndarray | None = None, spread: float = 0.05):
    rng = np.random.default_rng(seed)
    base = center if center is not None else np.zeros(dim)
    return base + rng.normal(scale=spread, size=(n, dim))


# --- kmeans (pure function) -----------------------------------------------------


def test_kmeans_separates_two_well_separated_blobs():
    rng = np.random.default_rng(42)
    blob_a = rng.normal(loc=0.0, scale=0.1, size=(20, 5))
    blob_b = rng.normal(loc=10.0, scale=0.1, size=(20, 5))
    vectors = np.vstack([blob_a, blob_b])

    labels, centroids = kmeans(vectors, k=2, seed=0)

    # Every point in the first 20 shares one label, every point in the
    # second 20 shares the other — a real separation, not "close enough".
    assert len(set(labels[:20])) == 1
    assert len(set(labels[20:])) == 1
    assert labels[0] != labels[20]
    assert centroids.shape == (2, 5)


def test_kmeans_is_deterministic_given_a_seed():
    rng = np.random.default_rng(1)
    vectors = rng.normal(size=(30, 8))

    labels_a, _ = kmeans(vectors, k=3, seed=7)
    labels_b, _ = kmeans(vectors, k=3, seed=7)

    assert np.array_equal(labels_a, labels_b)


def test_kmeans_k_is_capped_at_number_of_points():
    vectors = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    labels, centroids = kmeans(vectors, k=10, seed=0)
    assert centroids.shape[0] == 3


# --- choose_k ---------------------------------------------------------------


def test_choose_k_returns_one_for_zero_or_one_documents():
    assert choose_k(0) == 1
    assert choose_k(1) == 1


def test_choose_k_grows_with_document_count():
    assert choose_k(300) > choose_k(30) > choose_k(3)


# --- project_2d (PCA via SVD) -------------------------------------------------


def test_project_2d_returns_correct_shape():
    centroids = np.random.default_rng(0).normal(size=(5, 1024))
    positions = project_2d(centroids)
    assert positions.shape == (5, 2)


def test_project_2d_single_cluster_is_the_origin():
    positions = project_2d(np.array([[1.0, 2.0, 3.0]]))
    assert positions.shape == (1, 2)
    assert tuple(positions[0]) == (0.0, 0.0)


def test_project_2d_preserves_separation_of_distinct_centroids():
    # Two very different centroids should not collapse to the same 2D point.
    centroids = np.array([[0.0] * 1024, [50.0] * 1024])
    positions = project_2d(centroids)
    assert not np.allclose(positions[0], positions[1])


# --- cluster_documents: known semantic groupings --------------------------------


def test_documents_about_the_same_topic_cluster_together():
    # Two synthetic "topics" — tight blobs far apart in embedding space,
    # standing in for "documents about the same thing embed similarly".
    topic_a_center = np.zeros(EMBEDDING_DIM)
    topic_b_center = np.full(EMBEDDING_DIM, 20.0)

    documents = []
    for i in range(6):
        documents.append(
            {
                "id": f"doc-a-{i}",
                "chunk_embeddings": _seeded_random_unit_vectors(
                    3, EMBEDDING_DIM, seed=i, center=topic_a_center
                ).tolist(),
            }
        )
    for i in range(6):
        documents.append(
            {
                "id": f"doc-b-{i}",
                "chunk_embeddings": _seeded_random_unit_vectors(
                    3, EMBEDDING_DIM, seed=100 + i, center=topic_b_center
                ).tolist(),
            }
        )

    result = cluster_documents(documents, seed=0)

    by_doc = {a.document_id: a.cluster_index for a in result.assignments}
    a_clusters = {by_doc[f"doc-a-{i}"] for i in range(6)}
    b_clusters = {by_doc[f"doc-b-{i}"] for i in range(6)}
    # "More often than not" per the exit criteria — every topic-A doc
    # landed in exactly one cluster, distinct from topic B's.
    assert len(a_clusters) == 1
    assert len(b_clusters) == 1
    assert a_clusters != b_clusters


def test_documents_with_no_chunks_are_excluded_not_crashed_on():
    documents = [
        {"id": "doc-1", "chunk_embeddings": [[0.1] * EMBEDDING_DIM]},
        {"id": "doc-2", "chunk_embeddings": []},  # not yet embedded, or extract-only
    ]
    result = cluster_documents(documents, seed=0)
    assigned_ids = {a.document_id for a in result.assignments}
    assert assigned_ids == {"doc-1"}


def test_empty_document_set_returns_empty_result():
    result = cluster_documents([], seed=0)
    assert result.assignments == []
    assert result.cluster_positions == []


# --- run_clustering_job orchestration -------------------------------------------


class _FakeGraphStorage:
    def __init__(self, documents: list[dict]):
        self.documents = documents
        self.replace_calls: list[dict] = []

    async def get_ready_documents_with_chunk_embeddings(self, *, user_jwt):
        return self.documents

    async def replace_clusters(self, *, user_jwt, user_id, cluster_positions, assignments):
        self.replace_calls.append(
            {
                "user_id": user_id,
                "cluster_positions": cluster_positions,
                "assignments": assignments,
            }
        )


@pytest.fixture(autouse=True)
def _reset():
    yield
    cluster_module.set_graph_storage(None)


@pytest.mark.asyncio
async def test_run_clustering_job_replaces_clusters_and_returns_count():
    documents = [
        {"id": "doc-1", "chunk_embeddings": [[0.0] * EMBEDDING_DIM]},
        {"id": "doc-2", "chunk_embeddings": [[10.0] * EMBEDDING_DIM]},
    ]
    storage = _FakeGraphStorage(documents)
    cluster_module.set_graph_storage(storage)

    count = await run_clustering_job(user_jwt="t", user_id="u1")

    assert count == 2
    assert len(storage.replace_calls) == 1
    assert storage.replace_calls[0]["user_id"] == "u1"
    assert len(storage.replace_calls[0]["assignments"]) == 2


# --- failures are logged, not lost (regression: no traceback appeared -----------
# --- in production logs for a real failure until this was added) ---------------


class _FailingGraphStorage:
    async def get_ready_documents_with_chunk_embeddings(self, *, user_jwt):
        raise ValueError("could not convert string to float: '[-0.045, 0.03]'")

    async def replace_clusters(self, **kwargs):
        raise AssertionError("should never be reached")


@pytest.mark.asyncio
async def test_run_clustering_job_returns_sentinel_and_logs_on_failure(caplog):
    cluster_module.set_graph_storage(_FailingGraphStorage())

    import logging

    with caplog.at_level(logging.ERROR):
        count = await run_clustering_job(user_jwt="t", user_id="u1")

    assert count == -1
    assert any("run_clustering_job failed" in r.message for r in caplog.records)


# --- timing: 300-document seed set ----------------------------------------------


def test_clustering_completes_within_time_bound_for_300_documents():
    documents = []
    rng = np.random.default_rng(0)
    for i in range(300):
        center = rng.normal(scale=5.0, size=EMBEDDING_DIM)
        documents.append(
            {
                "id": f"doc-{i}",
                "chunk_embeddings": _seeded_random_unit_vectors(
                    4, EMBEDDING_DIM, seed=i, center=center
                ).tolist(),
            }
        )

    start = time.monotonic()
    result = cluster_documents(documents, seed=0)
    elapsed = time.monotonic() - start

    assert len(result.assignments) == 300
    # Generous bound for local/CI hardware — see module docstring for
    # why this isn't the number that matters for Render's real instance.
    assert elapsed < 30.0, f"clustering 300 documents took {elapsed:.1f}s"
