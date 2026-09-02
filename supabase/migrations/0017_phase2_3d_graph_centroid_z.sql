-- 3D brain graph rendering upgrade — extends Stage 2.1's 2D PCA
-- projection (centroid_x/centroid_y) to 3D. No backfill needed:
-- replace_graph fully replaces every cluster row on the next recluster
-- (which already runs automatically after every embed), same as how
-- centroid_x/centroid_y themselves were introduced. default 0 exists
-- only so the column can be added not-null in one step; every real row
-- gets a real value on its next recluster.

alter table clusters add column centroid_z double precision not null default 0;
