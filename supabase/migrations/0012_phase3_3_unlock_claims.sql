-- Stage 3.3 — unlock_claims. An unlock proves the caller had the right
-- passphrase (server test-decrypts one sealed_chunks row with the
-- derived key the client sent for that single request — see
-- app/core/sealed_storage.py's create_unlock_claim) and in exchange gets
-- a short-lived claim scoped to exactly one document. The claim is
-- state, not a signed token, so expiry is enforced by comparing
-- expires_at against Postgres's own now() server-side — a client can't
-- extend or forge validity by lying about the clock.
--
-- expires_at is computed and stored at issue time (now() + 15 minutes)
-- rather than recomputed from created_at on every check, so the TTL is
-- fixed at issuance even if the constant changes later.
--
-- No update policy: a claim's expiry is never extended in place: a
-- renewed unlock creates a new row instead of mutating this one.

create table unlock_claims (
  id uuid primary key default extensions.uuid_generate_v4(),
  document_id uuid not null references documents (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index unlock_claims_user_id_idx on unlock_claims (user_id);
create index unlock_claims_document_id_idx on unlock_claims (document_id);

alter table unlock_claims enable row level security;

create policy unlock_claims_select_own on unlock_claims
  for select using (auth.uid() = user_id);
create policy unlock_claims_insert_own on unlock_claims
  for insert with check (auth.uid() = user_id);
create policy unlock_claims_delete_own on unlock_claims
  for delete using (auth.uid() = user_id);
