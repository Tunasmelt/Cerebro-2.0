-- User-triggered lease recovery for ingest work interrupted by a process
-- restart. This keeps the free-tier in-process worker model while making
-- persisted jobs resumable when the owner next opens Documents.
alter table ingest_jobs add column if not exists updated_at timestamptz not null default now();
alter table ingest_jobs add column if not exists lease_expires_at timestamptz;

-- Extraction may have committed chunks immediately before a process died.
-- Make replay idempotent instead of duplicating ordinals on recovery.
alter table chunks
  add constraint chunks_document_ordinal_unique unique (document_id, ordinal);

create or replace function set_ingest_job_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists ingest_jobs_set_updated_at on ingest_jobs;
create trigger ingest_jobs_set_updated_at
before update on ingest_jobs
for each row execute function set_ingest_job_updated_at();

create or replace function claim_recoverable_ingest_jobs(
  stale_before timestamptz,
  lease_until timestamptz
)
returns table (document_id uuid, state text, source text)
language sql
security invoker
set search_path = public
as $$
  with claimed as (
    update ingest_jobs
    set lease_expires_at = lease_until
    where user_id = auth.uid()
      and state in ('normalizing', 'extracting', 'embedding')
      and updated_at < stale_before
      and (lease_expires_at is null or lease_expires_at < now())
    returning ingest_jobs.document_id, ingest_jobs.state
  )
  select claimed.document_id, claimed.state, documents.source
  from claimed join documents on documents.id = claimed.document_id;
$$;
