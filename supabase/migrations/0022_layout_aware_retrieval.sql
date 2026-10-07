-- Layout-aware multimodal retrieval. The existing chunks table remains the
-- retrieval/citation anchor; these tables add versioned structural evidence.

create table layout_generations (
  id uuid primary key default extensions.uuid_generate_v4(),
  document_id uuid not null references documents (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  version integer not null,
  state text not null default 'building'
    check (state in ('building', 'partial', 'active', 'retired', 'failed')),
  checkpoint jsonb not null default '{}'::jsonb,
  error_code text,
  completeness double precision not null default 0
    check (completeness >= 0 and completeness <= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (document_id, id)
);

create table document_surfaces (
  id uuid primary key default extensions.uuid_generate_v4(),
  document_id uuid not null references documents (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  surface_index integer not null,
  kind text not null check (kind in ('pdf_page', 'image', 'structured_text')),
  page_number integer,
  width double precision,
  height double precision,
  render_path text,
  source_hash text,
  created_at timestamptz not null default now(),
  unique (document_id, surface_index)
);

create table document_regions (
  id uuid primary key default extensions.uuid_generate_v4(),
  generation_id uuid not null references layout_generations (id) on delete cascade,
  surface_id uuid not null references document_surfaces (id) on delete cascade,
  document_id uuid not null references documents (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  ordinal integer not null,
  region_type text not null check (region_type in (
    'heading', 'paragraph', 'list', 'code', 'table', 'chart', 'image',
    'caption', 'footnote'
  )),
  reading_order integer not null,
  parent_region_id uuid references document_regions (id) on delete set null,
  heading_level integer check (heading_level between 1 and 6),
  bbox jsonb,
  text_start integer,
  text_end integer,
  content text not null default '',
  semantic_summary text,
  extraction_source text not null default 'local'
    check (extraction_source in ('local', 'vision', 'merged')),
  meta jsonb not null default '{}'::jsonb,
  constraint document_regions_bbox_shape check (
    bbox is null or (jsonb_typeof(bbox) = 'array' and jsonb_array_length(bbox) = 4)
  ),
  constraint document_regions_text_offsets check (
    (text_start is null and text_end is null)
    or (text_start >= 0 and text_end >= text_start)
  ),
  unique (generation_id, ordinal)
);

create table region_relations (
  id uuid primary key default extensions.uuid_generate_v4(),
  document_id uuid not null references documents (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  source_region_id uuid not null references document_regions (id) on delete cascade,
  target_region_id uuid not null references document_regions (id) on delete cascade,
  relation_type text not null check (
    relation_type in ('caption_of', 'references', 'continuation_of')
  ),
  confidence double precision,
  unique (source_region_id, target_region_id, relation_type),
  check (source_region_id <> target_region_id)
);

alter table documents add column layout_version integer not null default 1;
alter table documents add column layout_status text not null default 'legacy'
  check (layout_status in ('legacy', 'building', 'partial', 'ready', 'failed'));
alter table documents add column active_layout_generation uuid
  references layout_generations (id) on delete set null;

alter table chunks add column generation_id uuid
  references layout_generations (id) on delete cascade;
alter table chunks add column region_id uuid
  references document_regions (id) on delete set null;
alter table chunks add column representation_type text not null default 'text'
  check (representation_type in ('text', 'caption', 'visual'));

-- Adopt current ready chunks as immutable legacy generations. Sealed content
-- has no chunks and deliberately receives no plaintext layout generation.
insert into layout_generations (document_id, user_id, version, state, completeness)
select distinct d.id, d.user_id, 1, 'active', 1
from documents d
join chunks c on c.document_id = d.id
where d.status <> 'sealed';

update documents d
set active_layout_generation = g.id,
    layout_status = 'ready'
from layout_generations g
where g.document_id = d.id and g.version = 1 and g.state = 'active';

update chunks c
set generation_id = d.active_layout_generation
from documents d
where d.id = c.document_id and d.active_layout_generation is not null;

alter table chunks drop constraint if exists chunks_document_ordinal_unique;
alter table chunks add constraint chunks_generation_ordinal_unique
  unique (document_id, generation_id, ordinal);

create index layout_generations_document_idx on layout_generations (document_id, state);
create index document_surfaces_document_idx on document_surfaces (document_id, surface_index);
create index document_regions_generation_idx on document_regions (generation_id, reading_order);
create index document_regions_surface_idx on document_regions (surface_id, reading_order);
create index region_relations_source_idx on region_relations (source_region_id);
create index region_relations_target_idx on region_relations (target_region_id);
create index chunks_region_idx on chunks (region_id);
create index chunks_generation_idx on chunks (generation_id);

alter table layout_generations enable row level security;
alter table document_surfaces enable row level security;
alter table document_regions enable row level security;
alter table region_relations enable row level security;

create policy layout_generations_select_own on layout_generations for select
  using (auth.uid() = user_id);
create policy layout_generations_insert_own on layout_generations for insert
  with check (auth.uid() = user_id);
create policy layout_generations_update_own on layout_generations for update
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy layout_generations_delete_own on layout_generations for delete
  using (auth.uid() = user_id);

create policy document_surfaces_select_own on document_surfaces for select
  using (auth.uid() = user_id);
create policy document_surfaces_insert_own on document_surfaces for insert
  with check (auth.uid() = user_id);
create policy document_surfaces_update_own on document_surfaces for update
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy document_surfaces_delete_own on document_surfaces for delete
  using (auth.uid() = user_id);

create policy document_regions_select_own on document_regions for select
  using (auth.uid() = user_id);
create policy document_regions_insert_own on document_regions for insert
  with check (auth.uid() = user_id);
create policy document_regions_update_own on document_regions for update
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy document_regions_delete_own on document_regions for delete
  using (auth.uid() = user_id);

create policy region_relations_select_own on region_relations for select
  using (auth.uid() = user_id);
create policy region_relations_insert_own on region_relations for insert
  with check (auth.uid() = user_id);
create policy region_relations_update_own on region_relations for update
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy region_relations_delete_own on region_relations for delete
  using (auth.uid() = user_id);

insert into storage.buckets (id, name, public)
values ('evidence', 'evidence', false)
on conflict (id) do nothing;

create policy evidence_select_own on storage.objects for select using (
  bucket_id = 'evidence' and (storage.foldername(name))[1] = auth.uid()::text
);
create policy evidence_insert_own on storage.objects for insert with check (
  bucket_id = 'evidence' and (storage.foldername(name))[1] = auth.uid()::text
);
create policy evidence_update_own on storage.objects for update using (
  bucket_id = 'evidence' and (storage.foldername(name))[1] = auth.uid()::text
) with check (
  bucket_id = 'evidence' and (storage.foldername(name))[1] = auth.uid()::text
);
create policy evidence_delete_own on storage.objects for delete using (
  bucket_id = 'evidence' and (storage.foldername(name))[1] = auth.uid()::text
);

drop function if exists match_chunks_vector(halfvec(1024), int, text);
create or replace function match_chunks_vector(
  query_embedding halfvec(1024), match_count int, primary_provider text default 'jina'
)
returns table (
  id uuid, document_id uuid, ordinal int, content text, meta jsonb, distance float
)
language sql stable set search_path = public, extensions as $$
  select chunks.id, chunks.document_id, chunks.ordinal, chunks.content,
    chunks.meta || jsonb_build_object(
      'generation_id', chunks.generation_id,
      'region_id', chunks.region_id,
      'representation_type', chunks.representation_type
    ),
    chunks.embedding <=> query_embedding as distance
  from chunks
  join documents on documents.id = chunks.document_id
  where chunks.embedding is not null
    and documents.embedding_provider = primary_provider
    and documents.status <> 'sealed'
    and (
      chunks.generation_id = documents.active_layout_generation
      or (documents.active_layout_generation is null and chunks.generation_id is null)
    )
  order by chunks.embedding <=> query_embedding
  limit match_count;
$$;

drop function if exists match_chunks_fts(text, int);
create or replace function match_chunks_fts(query_text text, match_count int)
returns table (
  id uuid, document_id uuid, ordinal int, content text, meta jsonb, rank float
)
language sql stable set search_path = public, extensions as $$
  select chunks.id, chunks.document_id, chunks.ordinal, chunks.content,
    chunks.meta || jsonb_build_object(
      'generation_id', chunks.generation_id,
      'region_id', chunks.region_id,
      'representation_type', chunks.representation_type
    ),
    ts_rank(chunks.content_tsv, websearch_to_tsquery('english', query_text)) as rank
  from chunks
  join documents on documents.id = chunks.document_id
  where chunks.content_tsv @@ websearch_to_tsquery('english', query_text)
    and documents.status <> 'sealed'
    and (
      chunks.generation_id = documents.active_layout_generation
      or (documents.active_layout_generation is null and chunks.generation_id is null)
    )
  order by rank desc
  limit match_count;
$$;

create or replace function activate_layout_generation(generation_to_activate uuid)
returns void
language plpgsql
security invoker
set search_path = public
as $$
declare
  selected_generation layout_generations%rowtype;
begin
  select target.* into selected_generation
  from layout_generations target
  where target.id = generation_to_activate
    and target.user_id = auth.uid()
  for update;

  if not found then
    raise exception 'layout_generation_not_found';
  end if;

  update chunks
  set embedding = null
  where document_id = selected_generation.document_id
    and generation_id is distinct from generation_to_activate;

  update layout_generations
  set state = 'retired', updated_at = now()
  where document_id = selected_generation.document_id
    and id <> generation_to_activate
    and state <> 'failed';

  update layout_generations
  set state = case when completeness < 1 then 'partial' else 'active' end,
      updated_at = now()
  where id = generation_to_activate;

  update documents
  set active_layout_generation = generation_to_activate,
      layout_version = selected_generation.version,
      layout_status = case
        when selected_generation.completeness < 1 then 'partial'
        else 'ready'
      end
  where id = selected_generation.document_id and user_id = auth.uid();
end;
$$;
