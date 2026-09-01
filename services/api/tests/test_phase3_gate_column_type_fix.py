"""Phase 3 Gate testing found a real bug: sealed_chunks.content_ciphertext
/salt/nonce were declared `bytea` (migration 0011), but sealed_storage.py
writes and reads them as plain base64 TEXT strings via PostgREST's JSON
REST interface everywhere — it never base64-decodes on the way in or
re-encodes on the way out, only calling base64.b64decode() right before
AESGCM.decrypt(). PostgREST does not auto-decode a JSON string into
bytea; the stored value came back corrupted (confirmed live: a real
binascii.Error crashed /unlock with a 500, for the document's own
legitimate owner, not just an attacker). Fixed by migration 0014,
altering these three columns to `text` — matching what the application
code always assumed. No test at the fake-httpx-transport level (like
test_stage_3_5_seal_storage.py) could ever have caught this, since a
fake transport just echoes back whatever JSON it's given — the mismatch
only exists against real Postgres/PostgREST column typing. This is a
static guard against ever reverting to bytea for these columns.
"""
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parents[3] / "supabase" / "migrations"


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )


def test_sealed_chunks_ciphertext_columns_end_as_text_not_bytea():
    fix_matches = list(MIGRATIONS_DIR.glob("*sealed_chunks_column_type_fix*.sql"))
    assert len(fix_matches) == 1, "expected exactly one column-type-fix migration"
    sql = _strip_sql_comments(fix_matches[0].read_text()).lower()

    for column in ("content_ciphertext", "salt", "nonce"):
        assert f"alter column {column} type text" in sql, (
            f"expected the fix migration to alter {column} to text"
        )

    # And nothing after it reverts any of these three columns back to
    # bytea (a later migration touching this table for an unrelated
    # reason must not silently regress the type).
    fix_name = fix_matches[0].name
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name <= fix_name:
            continue
        text = _strip_sql_comments(path.read_text()).lower()
        for column in ("content_ciphertext", "salt", "nonce"):
            assert f"alter column {column} type bytea" not in text, (
                f"{path.name} reverts sealed_chunks.{column} back to bytea"
            )
