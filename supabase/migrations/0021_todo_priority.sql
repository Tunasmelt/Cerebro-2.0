alter table todos
  add column priority text not null default 'medium'
  check (priority in ('low', 'medium', 'high'));

create index todos_user_priority_idx on todos (user_id, priority);
