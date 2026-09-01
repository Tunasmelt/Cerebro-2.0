-- Stage 2.5 — incremental clustering. Nearest-centroid placement for a
-- new upload needs the real 1024-dim cluster centroid to be meaningful
-- distance-wise — clusters.centroid_x/centroid_y is only the lossy 2D
-- PCA projection (Stage 2.1), fine for rendering, not for "which
-- cluster is this new document actually closest to". centroid_embedding
-- stores the same high-dim centroid_by_doc mean that kmeans() already
-- computes internally every full recluster, just persisted instead of
-- discarded after the 2D projection step.
--
-- document_clusters.placement_method distinguishes a row written by a
-- full recluster (every row gets touched, cluster positions can shift)
-- from one written by incremental placement (single new row, existing
-- clusters/rows never touched) — this is what
-- count_incremental_placements counts against the threshold that
-- triggers the next full recluster.

alter table clusters
  add column centroid_embedding halfvec(1024);

alter table document_clusters
  add column placement_method text not null default 'kmeans'
    check (placement_method in ('kmeans', 'incremental'));
