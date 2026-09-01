"""Stage 2.5 — incremental clustering.

Exit criteria: uploading one new document does not change the position
of unrelated existing nodes (nearest-centroid placement, no full
recluster) until INCREMENTAL_RECLUSTER_THRESHOLD is hit, at which point
placement falls back to a full recluster instead.
"""
import numpy as np
import pytest

from app.graph import cluster as cluster_module
from app.graph.cluster import (
    INCREMENTAL_RECLUSTER_THRESHOLD,
    find_nearest_cluster,
    place_new_document,
)

EMBEDDING_DIM = 1024


# --- find_nearest_cluster (pure function) -----------------------------------


def test_find_nearest_cluster_returns_none_for_empty_list():
    assert find_nearest_cluster(np.zeros(EMBEDDING_DIM), []) is None


def test_find_nearest_cluster_picks_the_closest_by_real_distance():
    document_centroid = np.zeros(EMBEDDING_DIM)
    clusters = [
        {"id": "far", "centroid_embedding": [50.0] * EMBEDDING_DIM},
        {"id": "near", "centroid_embedding": [1.0] * EMBEDDING_DIM},
    ]
    cluster_id, distance = find_nearest_cluster(document_centroid, clusters)
    assert cluster_id == "near"
    assert distance == pytest.approx(float(np.linalg.norm(np.ones(EMBEDDING_DIM))))


# --- place_new_document orchestration ---------------------------------------


class _FakeGraphStorage:
    def __init__(
        self,
        *,
        clusters: list[dict] | None = None,
        incremental_count: int = 0,
        chunk_embeddings: list[list[float]] | None = None,
    ):
        self.clusters = clusters if clusters is not None else []
        self.incremental_count = incremental_count
        self.chunk_embeddings = chunk_embeddings if chunk_embeddings is not None else []
        self.inserted: list[dict] = []
        self.recluster_calls = 0
        self.documents: list[dict] = []

    async def get_clusters_with_centroids(self, *, user_jwt):
        return self.clusters

    async def count_incremental_placements(self, *, user_jwt):
        return self.incremental_count

    async def get_document_chunk_embeddings(self, *, user_jwt, document_id):
        return self.chunk_embeddings

    async def insert_incremental_assignment(
        self, *, user_jwt, user_id, document_id, cluster_id, distance
    ):
        self.inserted.append(
            {
                "user_id": user_id,
                "document_id": document_id,
                "cluster_id": cluster_id,
                "distance": distance,
            }
        )

    # run_clustering_job's dependencies, only reached in the
    # full_recluster path.
    async def get_ready_documents_with_chunk_embeddings(self, *, user_jwt):
        self.recluster_calls += 1
        return self.documents

    async def replace_graph(self, **kwargs):
        pass


@pytest.fixture(autouse=True)
def _reset():
    yield
    cluster_module.set_graph_storage(None)


@pytest.mark.asyncio
async def test_place_new_document_returns_unclustered_when_no_clusters_exist():
    storage = _FakeGraphStorage(clusters=[])
    cluster_module.set_graph_storage(storage)

    result = await place_new_document(user_jwt="t", user_id="u1", document_id="doc-1")

    assert result == "unclustered"
    assert storage.inserted == []


@pytest.mark.asyncio
async def test_place_new_document_incremental_does_not_touch_unrelated_rows():
    storage = _FakeGraphStorage(
        clusters=[
            {"id": "cluster-a", "centroid_embedding": [0.0] * EMBEDDING_DIM},
            {"id": "cluster-b", "centroid_embedding": [50.0] * EMBEDDING_DIM},
        ],
        incremental_count=0,
        chunk_embeddings=[[1.0] * EMBEDDING_DIM],
    )
    cluster_module.set_graph_storage(storage)

    result = await place_new_document(user_jwt="t", user_id="u1", document_id="doc-new")

    assert result == "incremental"
    assert storage.recluster_calls == 0
    assert len(storage.inserted) == 1
    assert storage.inserted[0]["document_id"] == "doc-new"
    assert storage.inserted[0]["cluster_id"] == "cluster-a"


@pytest.mark.asyncio
async def test_place_new_document_falls_back_to_full_recluster_at_threshold():
    storage = _FakeGraphStorage(
        clusters=[{"id": "cluster-a", "centroid_embedding": [0.0] * EMBEDDING_DIM}],
        incremental_count=INCREMENTAL_RECLUSTER_THRESHOLD - 1,
        chunk_embeddings=[[1.0] * EMBEDDING_DIM],
    )
    cluster_module.set_graph_storage(storage)

    result = await place_new_document(user_jwt="t", user_id="u1", document_id="doc-new")

    assert result == "full_recluster"
    assert storage.recluster_calls == 1
    # Placement happened via the recluster job, not a direct insert.
    assert storage.inserted == []


@pytest.mark.asyncio
async def test_place_new_document_returns_unclustered_when_document_has_no_chunks():
    storage = _FakeGraphStorage(
        clusters=[{"id": "cluster-a", "centroid_embedding": [0.0] * EMBEDDING_DIM}],
        incremental_count=0,
        chunk_embeddings=[],
    )
    cluster_module.set_graph_storage(storage)

    result = await place_new_document(user_jwt="t", user_id="u1", document_id="doc-new")

    assert result == "unclustered"
    assert storage.inserted == []


@pytest.mark.asyncio
async def test_place_new_document_logs_and_returns_unclustered_on_failure(caplog):
    class _FailingStorage:
        async def get_clusters_with_centroids(self, *, user_jwt):
            raise ValueError("boom")

    cluster_module.set_graph_storage(_FailingStorage())

    import logging

    with caplog.at_level(logging.ERROR):
        result = await place_new_document(user_jwt="t", user_id="u1", document_id="doc-1")

    assert result == "unclustered"
    assert any("place_new_document failed" in r.message for r in caplog.records)
