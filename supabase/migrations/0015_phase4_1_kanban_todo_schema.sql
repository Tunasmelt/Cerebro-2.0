-- Stage 4.1 — boards, cards, todos. Same flat RLS pattern as every
-- other table (auth.uid() = user_id), per architecture-and-security.md's
-- security review section.
--
-- No separate `columns` table: a kanban column is just a name in
-- boards.columns (a small ordered jsonb array, e.g. ["Backlog","Doing",
-- "Done"]), and cards.column_name is a plain text value the app matches
-- against it. This keeps drag-drop able to rename/reorder columns
-- without a second table, at the cost of the DB not being able to
-- enforce "column_name is one of the board's own columns" — acceptable
-- here the same way `documents.status`'s check-constraint enum is
-- app-owned, not because integrity doesn't matter but because this
-- isn't a security boundary, just app-level data shape.
--
-- cards.position is a float (not int) specifically so drag-and-drop can
-- insert a card between two existing ones by averaging their positions,
-- without renumbering every other card in the column on every move.
--
-- document_id on both cards and todos is the "optional reference chip
-- into documents" the stage's exit criteria calls for — `on delete set
-- null` (not cascade): deleting a document shouldn't delete someone's
-- kanban card or todo, only clear the reference.

-- boards ------------------------------------------------------------------

create table boards (
  id uuid primary key default extensions.uuid_generate_v4(),
  user_id uuid not null references auth.users (id) on delete cascade,
  title text not null,
  columns jsonb not null default '["Backlog", "In Progress", "Done"]'::jsonb,
  created_at timestamptz not null default now()
);

create index boards_user_id_idx on boards (user_id);

alter table boards enable row level security;

create policy boards_select_own on boards
  for select using (auth.uid() = user_id);
create policy boards_insert_own on boards
  for insert with check (auth.uid() = user_id);
create policy boards_update_own on boards
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy boards_delete_own on boards
  for delete using (auth.uid() = user_id);

-- cards ---------------------------------------------------------------------

create table cards (
  id uuid primary key default extensions.uuid_generate_v4(),
  board_id uuid not null references boards (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  document_id uuid references documents (id) on delete set null,
  column_name text not null,
  title text not null,
  description text not null default '',
  position double precision not null default 0,
  created_at timestamptz not null default now()
);

create index cards_user_id_idx on cards (user_id);
create index cards_board_id_idx on cards (board_id);
create index cards_document_id_idx on cards (document_id);

alter table cards enable row level security;

create policy cards_select_own on cards
  for select using (auth.uid() = user_id);
create policy cards_insert_own on cards
  for insert with check (auth.uid() = user_id);
create policy cards_update_own on cards
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy cards_delete_own on cards
  for delete using (auth.uid() = user_id);

-- todos -----------------------------------------------------------------------

create table todos (
  id uuid primary key default extensions.uuid_generate_v4(),
  user_id uuid not null references auth.users (id) on delete cascade,
  document_id uuid references documents (id) on delete set null,
  title text not null,
  completed boolean not null default false,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);

create index todos_user_id_idx on todos (user_id);
create index todos_document_id_idx on todos (document_id);

alter table todos enable row level security;

create policy todos_select_own on todos
  for select using (auth.uid() = user_id);
create policy todos_insert_own on todos
  for insert with check (auth.uid() = user_id);
create policy todos_update_own on todos
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy todos_delete_own on todos
  for delete using (auth.uid() = user_id);
