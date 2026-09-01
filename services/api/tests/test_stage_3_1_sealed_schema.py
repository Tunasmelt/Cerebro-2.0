"""Stage 3.1 — sealed_chunks schema isolation. No live Postgres in CI (see
CLAUDE.md's testing gate — migrations apply directly to the real Supabase
project), so this statically inspects the migration SQL itself for the
exit criteria: sealed_chunks exists, is fully isolated from chunks
(no FK or view joins it into any chunks-based query), and has no
embedding column.
"""
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parents[3] / "supabase" / "migrations"


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )


def _sealed_chunks_migration() -> str:
    matches = list(MIGRATIONS_DIR.glob("*sealed_chunks*.sql"))
    assert len(matches) == 1, "expected exactly one sealed_chunks migration"
    return _strip_sql_comments(matches[0].read_text())


def test_sealed_chunks_table_exists():
    sql = _sealed_chunks_migration()
    assert "create table sealed_chunks" in sql


def test_sealed_chunks_has_no_embedding_column():
    sql = _sealed_chunks_migration()
    assert "embedding" not in sql.lower()


def test_sealed_chunks_has_no_foreign_key_to_or_from_chunks():
    sql = _sealed_chunks_migration()
    assert "references chunks" not in sql.lower()

    # And nothing in any other migration adds a FK/view pulling
    # sealed_chunks into a chunks-based query.
    sealed_migration_name = list(MIGRATIONS_DIR.glob("*sealed_chunks*.sql"))[0].name
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if path.name == sealed_migration_name:
            continue
        text = _strip_sql_comments(path.read_text()).lower()
        assert "references sealed_chunks" not in text
        assert "join sealed_chunks" not in text


def test_sealed_chunks_scoped_by_row_level_security():
    sql = _sealed_chunks_migration()
    assert "alter table sealed_chunks enable row level security" in sql
    assert "auth.uid() = user_id" in sql


def test_no_existing_view_or_query_joins_chunks_and_sealed_chunks():
    """Guards against a future migration accidentally wiring the two
    together — the retrieval path (retrieve.py) must never see sealed
    content."""
    retrieve_path = (
        Path(__file__).parents[1] / "app" / "retrieve" / "retrieve.py"
    )
    text = retrieve_path.read_text().lower()
    assert "sealed_chunks" not in text
