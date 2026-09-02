"""Stage 4.1 — boards/cards/todos schema. No live Postgres in CI (see
CLAUDE.md's testing gate — migrations apply directly to the real
Supabase project), so this statically inspects the migration SQL, same
pattern as test_stage_3_1_sealed_schema.py.

Exit criteria: boards, cards, todos exist, scoped to user_id only,
optional reference chip into documents.
"""
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parents[3] / "supabase" / "migrations"


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )


def _kanban_todo_migration() -> str:
    matches = list(MIGRATIONS_DIR.glob("*phase4_1_kanban_todo_schema*.sql"))
    assert len(matches) == 1, "expected exactly one Stage 4.1 schema migration"
    return _strip_sql_comments(matches[0].read_text())


def test_boards_cards_todos_tables_exist():
    sql = _kanban_todo_migration().lower()
    assert "create table boards" in sql
    assert "create table cards" in sql
    assert "create table todos" in sql


def test_all_three_tables_have_row_level_security_enabled():
    sql = _kanban_todo_migration().lower()
    for table in ("boards", "cards", "todos"):
        assert f"alter table {table} enable row level security" in sql


def test_all_three_tables_scoped_by_flat_user_id_rls():
    sql = _kanban_todo_migration().lower()
    # Same flat auth.uid() = user_id pattern as every other table —
    # count of "auth.uid() = user_id" should be 4 per table (select,
    # insert with check, update using + with check, delete).
    assert sql.count("auth.uid() = user_id") >= 12  # 4 policies x 3 tables


def test_cards_and_todos_have_optional_document_reference_chip():
    sql = _kanban_todo_migration().lower()
    # "optional" = nullable (no `not null`) and non-destructive on
    # delete (set null, not cascade) — deleting a document must never
    # delete someone's kanban card or todo.
    assert "document_id uuid references documents (id) on delete set null" in sql
    assert sql.count("document_id uuid references documents (id) on delete set null") == 2


def test_cards_reference_boards_with_cascade_delete():
    sql = _kanban_todo_migration().lower()
    assert "board_id uuid not null references boards (id) on delete cascade" in sql


def test_cards_have_a_position_field_for_persisting_order():
    sql = _kanban_todo_migration().lower()
    assert "position double precision not null" in sql
