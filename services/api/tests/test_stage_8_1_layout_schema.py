"""Layout-aware retrieval schema contract.

CI has no live Supabase instance, so migration invariants are inspected in
the same way as the sealed-tier and kanban schema gates.
"""
from pathlib import Path


MIGRATIONS = Path(__file__).parents[3] / "supabase" / "migrations"


def _sql() -> str:
    matches = list(MIGRATIONS.glob("*layout_aware_retrieval*.sql"))
    assert len(matches) == 1, "expected one layout-aware retrieval migration"
    return matches[0].read_text().lower()


def test_layout_tables_and_chunk_links_exist():
    sql = _sql()
    for table in (
        "layout_generations",
        "document_surfaces",
        "document_regions",
        "region_relations",
    ):
        assert f"create table {table}" in sql
    assert "add column generation_id uuid" in sql
    assert "add column region_id uuid" in sql
    assert "add column representation_type text" in sql


def test_layout_tables_are_rls_scoped_to_owner():
    sql = _sql()
    for table in (
        "layout_generations",
        "document_surfaces",
        "document_regions",
        "region_relations",
    ):
        assert f"alter table {table} enable row level security" in sql
    assert sql.count("auth.uid() = user_id") >= 16


def test_evidence_bucket_is_private_and_owner_scoped():
    sql = _sql()
    assert "('evidence', 'evidence', false)" in sql
    assert "bucket_id = 'evidence'" in sql
    assert "(storage.foldername(name))[1] = auth.uid()::text" in sql


def test_retrieval_functions_filter_to_active_generation():
    sql = _sql()
    assert sql.count("chunks.generation_id = documents.active_layout_generation") >= 2
    assert "create or replace function match_chunks_vector" in sql
    assert "create or replace function match_chunks_fts" in sql


def test_activation_is_an_owner_scoped_transactional_rpc():
    sql = _sql()
    assert "create or replace function activate_layout_generation" in sql
    assert "target.user_id = auth.uid()" in sql
    assert "active_layout_generation = generation_to_activate" in sql
    assert "embedding = null" in sql


def test_region_shape_and_relation_enums_are_constrained():
    sql = _sql()
    for region_type in (
        "heading",
        "paragraph",
        "list",
        "code",
        "table",
        "chart",
        "image",
        "caption",
        "footnote",
    ):
        assert f"'{region_type}'" in sql
    for relation_type in ("caption_of", "references", "continuation_of"):
        assert f"'{relation_type}'" in sql
    assert "jsonb_array_length(bbox) = 4" in sql
