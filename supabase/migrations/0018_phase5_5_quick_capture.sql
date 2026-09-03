-- Stage 5.5 — quick capture (journaling as ingest). A captured thought
-- feeds into the *existing* documents/chunks pipeline, not a parallel
-- one — `source` distinguishes it from an uploaded file ('upload' is
-- what every existing row already implicitly is, backfilled as the
-- default) with zero special-casing anywhere downstream of extract.py.
--
-- captured_text holds the raw text for a capture row only — there is no
-- file, so no originals/indexed Storage object exists to read it back
-- from (this is what lets extract.py skip the Stage 1.2 normalize step
-- and any storage round-trip entirely for this source type).
-- storage_path/original_storage_path are already nullable columns
-- (Stage 0.2's original schema never marked them not-null), so no
-- change was needed there.

alter table documents add column source text not null default 'upload'
  check (source in ('upload', 'capture'));
alter table documents add column captured_text text;
